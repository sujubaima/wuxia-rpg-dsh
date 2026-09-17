#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次 go/judge 调用内的暂存、事件与触发归约生命周期。"""
from collections import deque

from quest.models import import_legacy_quests, normalize_quest_state
from quest.projection import notice_results, project_clues
from quest.world_facts import normalize_world_facts

from common import dao as dq
from store import save_manager as sm
from world import scene as sc
from settle import engine_state as est
from quest.events import EventFactory, EventRequest
from settle.mutation_executor import MutationContext
from quest.registry import DEFAULT_TRIGGER_REGISTRY, TriggerOutcome


class SettlementSession:
    MAX_EVENTS = 512
    MAX_MUTATIONS = 512
    MAX_TRIGGER_CALLS = 1024

    def __init__(self, slot, explore, executor, origin, trigger_registry=None):
        self.slot = slot
        self.explore = explore
        self.executor = executor
        self.factory = EventFactory(slot, origin)
        self.triggers = trigger_registry or DEFAULT_TRIGGER_REGISTRY
        self.events = []
        self._queue = deque()
        self._mutation_count = 0
        self._trigger_calls = 0
        self._draining = False
        self._closed = False
        self._committed = False
        self.world_facts = None
        self.quest_state = None
        self.world_facts_dirty = False
        self.quest_state_dirty = False
        self.pending_notices = []
        self.gm_hints = []

    def __enter__(self):
        if est._SESSION is not None:
            raise RuntimeError("不支持嵌套 SettlementSession")
        est._TXN = {}
        est._NEW_CHAR_STAGED = {}
        est._SCENE_STAGED = {}
        est._SCENE_TYPE_STAGED = {}
        est._MERCHANT_STAGED = None
        est._MERCHANT_DIRTY = False
        if getattr(self.triggers, "uses_quest_state", False):
            self.world_facts = normalize_world_facts(sm.read_world_facts(self.slot))
            raw_quest_state = sm.read_quest_state(self.slot)
            self.quest_state = normalize_quest_state(raw_quest_state)
            if raw_quest_state and raw_quest_state != self.quest_state:
                self.quest_state_dirty = True
            if import_legacy_quests(self.explore, self.quest_state):
                self.quest_state_dirty = True
                self.refresh_quest_projection()
        else:
            self.world_facts = normalize_world_facts({})
            self.quest_state = normalize_quest_state({})
        est._SESSION = self
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def apply_mutations(self, mutations):
        mutations = list(mutations or [])
        self._mutation_count += len(mutations)
        if self._mutation_count > self.MAX_MUTATIONS:
            return [self._failure("状态变更归约超过上限，可能存在触发循环")]
        context = MutationContext(self.slot, self.explore, self.factory, self)
        execution = self.executor.execute_batch(context, mutations)
        results = list(execution.results)
        if all(r.get("ok") for r in results):
            self._enqueue_events(execution.events)
            if not self._draining:
                results.extend(self._drain())
        return results

    def emit(self, event_type, payload=None, origin=None):
        self._enqueue_events((self.factory.create(event_type, payload, origin),))
        return [] if self._draining else self._drain()

    def emit_request(self, request):
        self._enqueue_events((self.factory.from_request(request),))
        return [] if self._draining else self._drain()

    def _enqueue_events(self, events):
        for event in events:
            if len(self.events) + len(self._queue) >= self.MAX_EVENTS:
                raise RuntimeError("领域事件归约超过上限，可能存在触发循环")
            self._queue.append(event)

    def _drain(self):
        if self._draining:
            return []
        results = []
        self._draining = True
        try:
            while self._queue:
                event = self._queue.popleft()
                self.events.append(event)
                for handler in self.triggers.matching(event):
                    self._trigger_calls += 1
                    if self._trigger_calls > self.MAX_TRIGGER_CALLS:
                        self._queue.clear()
                        return results + [self._failure("触发器归约超过上限，可能存在触发循环")]
                    outcome = handler(event, self)
                    if outcome is None:
                        continue
                    if not isinstance(outcome, TriggerOutcome):
                        self._queue.clear()
                        return results + [self._failure("触发器必须返回 TriggerOutcome 或 None")]
                    if outcome.mutations:
                        generated = self.apply_mutations(outcome.mutations)
                        results.extend(generated)
                        if not all(r.get("ok") for r in generated):
                            self._queue.clear()
                            return results
                    for request in outcome.events:
                        if not isinstance(request, EventRequest):
                            self._queue.clear()
                            return results + [self._failure("触发器事件必须为 EventRequest")]
                        self._enqueue_events((self.factory.from_request(request),))
        except Exception as exc:
            self._queue.clear()
            return results + [self._failure(f"触发器结算异常：{exc}")]
        finally:
            self._draining = False
        return results

    def mark_world_facts_dirty(self):
        self.world_facts_dirty = True

    def mark_quest_state_dirty(self):
        self.quest_state_dirty = True
        self.refresh_quest_projection()

    def refresh_quest_projection(self):
        if self.quest_state and self.quest_state.get("definitions"):
            self.explore["任务摘要及进度"] = project_clues(self.quest_state)

    def add_notices(self, notices):
        self.pending_notices.extend(notices or [])

    def add_hints(self, hints):
        for hint in hints or []:
            if hint not in self.gm_hints:
                self.gm_hints.append(hint)

    def public_notice_results(self):
        return notice_results(self.pending_notices) if self._committed else []

    def commit(self):
        if self._closed:
            raise RuntimeError("SettlementSession 已关闭")
        for name, char in est._NEW_CHAR_STAGED.items():
            dq.write_character(name, char)
        for name, char in est._TXN.items():
            if name not in est._NEW_CHAR_STAGED:
                dq.update_char(name, char)
        sc.commit_staged(self.slot, est._SCENE_STAGED, est._SCENE_TYPE_STAGED)
        if est._MERCHANT_DIRTY:
            sm.write_merchant_cache(self.slot, est._MERCHANT_STAGED or {})
        if self.world_facts_dirty:
            sm.write_world_facts(self.slot, self.world_facts)
        if self.quest_state_dirty:
            sm.write_quest_state(self.slot, self.quest_state)
        self._committed = True

    def close(self):
        if self._closed:
            return
        est._TXN = None
        est._NEW_CHAR_STAGED = None
        est._SCENE_STAGED = None
        est._SCENE_TYPE_STAGED = None
        est._MERCHANT_STAGED = None
        est._MERCHANT_DIRTY = False
        est._SESSION = None
        self._closed = True

    @staticmethod
    def _failure(message):
        return {"ok": False, "msg": message, "_结算错误": True}
