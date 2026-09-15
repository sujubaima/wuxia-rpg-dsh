#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 mutation 注册、应用与领域事件投影。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MutationContext:
    slot: int
    explore: dict
    event_factory: object
    session: object = None


@dataclass(frozen=True)
class MutationSpec:
    apply: object
    snapshot: object = None
    project: object = None


@dataclass(frozen=True)
class MutationExecution:
    results: tuple
    events: tuple


class MutationExecutor:
    def __init__(self):
        self._registry = {}

    def register(self, kind, apply, snapshot=None, project=None):
        if not isinstance(kind, str) or not kind:
            raise ValueError("mutation kind 必须为非空字符串")
        if kind in self._registry:
            raise ValueError(f"mutation kind 重复注册【{kind}】")
        self._registry[kind] = MutationSpec(apply, snapshot, project)
        return self

    def execute(self, context, mutation):
        if not isinstance(mutation, dict):
            return MutationExecution((self._failure("非法状态变更条目"),), ())
        kind = mutation.get("类型")
        spec = self._registry.get(kind)
        if spec is None:
            return MutationExecution((self._failure(f"未知状态变更类型【{kind}】"),), ())
        try:
            before = spec.snapshot(context, mutation) if spec.snapshot else None
            raw = spec.apply(context, mutation)
            results = raw if isinstance(raw, list) else [raw]
            normalized = []
            for result in results:
                if not isinstance(result, dict):
                    result = {"ok": False, "msg": "mutation handler 返回值非法"}
                if not result.get("ok"):
                    result["_结算错误"] = True
                normalized.append(result)
            events = []
            if normalized and all(r.get("ok") for r in normalized) and spec.project:
                after = spec.snapshot(context, mutation) if spec.snapshot else None
                events = list(spec.project(context, mutation, before, after, normalized) or [])
            return MutationExecution(tuple(normalized), tuple(events))
        except (KeyError, TypeError, ValueError) as exc:
            return MutationExecution((self._failure(str(exc)),), ())

    def execute_batch(self, context, mutations):
        results = []
        events = []
        for mutation in mutations:
            execution = self.execute(context, mutation)
            results.extend(execution.results)
            events.extend(execution.events)
        if not all(r.get("ok") for r in results):
            events = []
        return MutationExecution(tuple(results), tuple(events))

    @staticmethod
    def _failure(message):
        return {"ok": False, "msg": message, "_结算错误": True}
