#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领域事件、mutation executor 与同步触发归约回归。"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from quest.events import (EventCodecV1, EventFactory, EventRequest,
                                  STAMINA_CHANGED, TIME_ADVANCED)
from settle.engine_actions import _ACTION_HANDLERS, build_mutation_executor
from settle.engine_io import (_read_merchant_cache, _stage_new_char,
                              _write_merchant_cache)
from settle.mutation_executor import MutationExecutor
from settle.settlement import SettlementSession
from quest.registry import TriggerOutcome, TriggerRegistry


class DomainEventTest(unittest.TestCase):
    def test_factory_freezes_payload_and_codec_round_trips(self):
        payload = {"nested": {"values": [1, 2]}}
        event = EventFactory(3, "judge").create("test.created", payload)
        payload["nested"]["values"].append(3)
        self.assertEqual(event.get("nested")["values"], (1, 2))
        with self.assertRaises(TypeError):
            event.payload["new"] = True
        encoded = EventCodecV1.encode(event)
        encoded["future"] = "ignored"
        decoded = EventCodecV1.decode(encoded)
        self.assertEqual(EventCodecV1.encode(decoded), EventCodecV1.encode(event))

    def test_factory_sequences_events_inside_one_settlement(self):
        factory = EventFactory(1, "go")
        self.assertEqual(factory.create("a").sequence, 1)
        self.assertEqual(factory.create("b").sequence, 2)


class MutationProjectionTest(unittest.TestCase):
    def test_stamina_event_uses_applied_delta(self):
        explore = {"体力": 99}
        executor = build_mutation_executor()
        with SettlementSession(1, explore, executor, "judge") as session:
            results = session.apply_mutations([{"类型": "体力", "操作": "加", "值": 20}])
            self.assertTrue(all(r["ok"] for r in results))
            event = next(e for e in session.events if e.type == STAMINA_CHANGED)
            self.assertEqual(event.payload_dict(), {"before": 99, "after": 100, "delta": 1})

    def test_talk_observe_requires_target_before_charging_cost(self):
        explore = {"体力": 20, "当前时间": 10}
        executor = build_mutation_executor()
        with SettlementSession(
            1, explore, executor, "go", TriggerRegistry()
        ) as session:
            results = _ACTION_HANDLERS["交谈观察"](
                1, explore, {"类型": "交谈观察", "目标": "  "}
            )
            self.assertFalse(all(r["ok"] for r in results), results)
            self.assertIn("须传入 目标", results[0]["msg"])
            self.assertEqual(explore, {"体力": 20, "当前时间": 10})
            self.assertEqual(session.events, [])

    def test_search_action_costs_two_stamina_and_two_ticks(self):
        explore = {"体力": 20, "当前时间": 10}
        executor = build_mutation_executor()
        with SettlementSession(
            1, explore, executor, "go", TriggerRegistry()
        ) as session:
            results = _ACTION_HANDLERS["搜查翻找"](
                1, explore, {"类型": "搜查翻找", "目标": "旧书柜"}
            )
            self.assertTrue(all(r["ok"] for r in results), results)
            self.assertEqual(explore["体力"], 18)
            self.assertEqual(explore["当前时间"], 12)
            self.assertEqual(
                [event.type for event in session.events],
                [STAMINA_CHANGED, TIME_ADVANCED],
            )

    def test_no_actual_change_emits_no_mechanical_event(self):
        explore = {"体力": 100}
        executor = build_mutation_executor()
        with SettlementSession(1, explore, executor, "judge") as session:
            results = session.apply_mutations([{"类型": "体力", "操作": "设", "值": 100}])
            self.assertTrue(all(r["ok"] for r in results))
            self.assertEqual(session.events, [])

    def test_narrative_event_mutation_is_rejected(self):
        explore = {"体力": 50}
        executor = build_mutation_executor()
        with SettlementSession(1, explore, executor, "judge") as session:
            results = session.apply_mutations([
                {"类型": "剧情事件", "事件": "发现密道", "数据": {"地点": "后院"}},
            ])
            self.assertFalse(all(r["ok"] for r in results))
            self.assertEqual(explore, {"体力": 50})
            self.assertEqual(session.events, [])


class TriggerSettlementTest(unittest.TestCase):
    @staticmethod
    def _toy_executor():
        executor = MutationExecutor()

        def apply(context, mutation):
            context.explore["value"] = context.explore.get("value", 0) + mutation["delta"]
            return {"ok": True, "msg": "changed", "变更": f"value={context.explore['value']}"}

        def snapshot(context, mutation):
            return context.explore.get("value", 0)

        def project(context, mutation, before, after, results):
            if before == after:
                return []
            return [context.event_factory.create(
                "test.value.changed", {"before": before, "after": after, "delta": after - before}
            )]

        executor.register("add", apply, snapshot, project)
        return executor

    def test_trigger_mutation_reaches_fixed_point_in_fifo_order(self):
        registry = TriggerRegistry()
        seen = []

        def exact(event, session):
            seen.append(("exact", event.get("after")))
            if event.get("after") == 1:
                return TriggerOutcome(mutations=({"类型": "add", "delta": 1},))
            return None

        def namespace(event, session):
            seen.append(("namespace", event.get("after")))
            return None

        registry.register("test.value.changed", exact)
        registry.register_namespace("test.value", namespace)
        state = {"value": 0}
        with SettlementSession(1, state, self._toy_executor(), "judge", registry) as session:
            results = session.apply_mutations([{"类型": "add", "delta": 1}])
            self.assertTrue(all(r["ok"] for r in results))
            self.assertEqual(state["value"], 2)
            self.assertEqual([e.get("after") for e in session.events], [1, 2])
            self.assertEqual(seen, [("exact", 1), ("namespace", 1),
                                    ("exact", 2), ("namespace", 2)])

    def test_trigger_can_emit_event_through_factory(self):
        registry = TriggerRegistry()
        registry.register(
            "test.value.changed",
            lambda event, session: TriggerOutcome(
                events=(EventRequest("test.followed", {"value": event.get("after")}),)
            ),
        )
        with SettlementSession(1, {"value": 0}, self._toy_executor(), "judge", registry) as session:
            results = session.apply_mutations([{"类型": "add", "delta": 1}])
            self.assertTrue(all(r["ok"] for r in results))
            self.assertEqual([e.type for e in session.events],
                             ["test.value.changed", "test.followed"])

    def test_loop_guard_returns_settlement_failure(self):
        registry = TriggerRegistry()
        registry.register(
            "test.value.changed",
            lambda event, session: TriggerOutcome(mutations=({"类型": "add", "delta": 1},)),
        )
        state = {"value": 0}
        with SettlementSession(1, state, self._toy_executor(), "judge", registry) as session:
            session.MAX_EVENTS = 3
            results = session.apply_mutations([{"类型": "add", "delta": 1}])
            self.assertTrue(any(not r["ok"] for r in results))
            self.assertIn("超过上限", results[-1]["msg"])


class StagingTest(unittest.TestCase):
    def test_merchant_cache_writes_only_on_commit(self):
        executor = MutationExecutor()
        with patch("settle.engine_io.sm.read_merchant_cache", return_value={"店-掌柜": {"库存": {}}}), \
             patch("settle.settlement.sm.write_merchant_cache") as write_cache, \
             patch("settle.settlement.sc.commit_staged"), \
             patch("settle.settlement.dq.write_character"), \
             patch("settle.settlement.dq.update_char"):
            with SettlementSession(1, {}, executor, "go") as session:
                data = _read_merchant_cache(1)
                data["店-掌柜"]["库存"]["药"] = 1
                _write_merchant_cache(1, data)
                write_cache.assert_not_called()
                session.commit()
            write_cache.assert_called_once_with(1, data)

    def test_staged_files_are_discarded_without_commit(self):
        executor = MutationExecutor()
        with patch("settle.engine_io.sm.read_merchant_cache", return_value={"店-掌柜": {"库存": {}}}), \
             patch("settle.engine_io.dq.read_character_file", return_value=None), \
             patch("settle.settlement.sm.write_merchant_cache") as write_cache, \
             patch("settle.settlement.dq.write_character") as write_character:
            with SettlementSession(1, {}, executor, "judge"):
                data = _read_merchant_cache(1)
                data["店-掌柜"]["库存"]["药"] = 1
                _write_merchant_cache(1, data)
                _stage_new_char(1, "新客", {"名称": "新客"})
            write_cache.assert_not_called()
            write_character.assert_not_called()


class SceneRegistrationTest(unittest.TestCase):
    """抵达登记校验 + 场景草稿采用后 SCENE_REGISTERED 事件与机械事实。"""

    @staticmethod
    def _draft(operations):
        """构造当前轮场景草稿（round=0），供 场景-采用草稿 mutation 读取。"""
        return {"round": 0, "operations": operations}

    def test_arrive_rejects_unregistered_destination(self):
        explore = {"当前位置": "苏州·平江路"}
        executor = build_mutation_executor()
        with SettlementSession(1, dict(explore), executor, "go") as session:
            results = session.apply_mutations([{"类型": "抵达", "位置": "苏州·幻影楼"}])
            self.assertFalse(results[0]["ok"])
            self.assertIn("未登记", results[0]["msg"])
            self.assertEqual(session.explore["当前位置"], "苏州·平江路")

    def test_arrive_accepts_baseline_scene(self):
        explore = {"当前位置": "苏州·平江路"}
        executor = build_mutation_executor()
        with SettlementSession(1, dict(explore), executor, "go") as session:
            results = session.apply_mutations([{"类型": "抵达", "位置": "苏州·观前街"}])
            self.assertTrue(results[0]["ok"], results[0].get("msg"))
            self.assertEqual(session.explore["当前位置"], "苏州·观前街")

    def test_arrive_accepts_scene_registered_in_same_turn(self):
        explore = {"当前位置": "苏州·平江路"}
        executor = build_mutation_executor()
        draft = self._draft([{"类型": "登记场景", "区域": "苏州", "场景": "烟雨渡"}])
        with patch("settle.engine_actions.sd.select_draft", return_value=draft), \
             patch("settle.engine_actions.sm.read_round", return_value=0), \
             SettlementSession(1, dict(explore), executor, "go") as session:
            results = session.apply_mutations([
                {"类型": "场景-采用草稿"},
                {"类型": "抵达", "位置": "苏州·烟雨渡"},
            ])
            self.assertTrue(all(r["ok"] for r in results), results)
            self.assertEqual(session.explore["当前位置"], "苏州·烟雨渡")

    def test_arrive_npc_bypasses_registration_check(self):
        explore = {"当前位置": "苏州·平江路"}
        executor = build_mutation_executor()
        with SettlementSession(1, dict(explore), executor, "go") as session:
            results = session.apply_mutations(
                [{"类型": "抵达", "角色": "路人甲", "位置": "苏州·幻影楼"}])
            self.assertTrue(results[0]["ok"], results[0].get("msg"))
            self.assertEqual(session.explore["人物位置"]["路人甲"], "苏州·幻影楼")

    def test_scene_draft_adoption_emits_event_and_mechanical_fact(self):
        from quest.events import FACT_CHANGED, SCENE_REGISTERED
        from quest.triggers import build_quest_trigger_registry
        executor = build_mutation_executor()
        draft = self._draft([{"类型": "登记场景", "区域": "苏州", "场景": "烟雨渡"}])
        with patch("settle.engine_actions.sd.select_draft", return_value=draft), \
             patch("settle.engine_actions.sm.read_round", return_value=0), \
             SettlementSession(1, {}, executor, "judge",
                               build_quest_trigger_registry()) as session:
            results = session.apply_mutations([{"类型": "场景-采用草稿"}])
            self.assertTrue(all(r["ok"] for r in results), results)
            scene_events = [e for e in session.events if e.type == SCENE_REGISTERED]
            self.assertEqual(len(scene_events), 1)
            self.assertEqual(scene_events[0].get("区域"), "苏州")
            self.assertEqual(scene_events[0].get("场景"), "烟雨渡")
            # 机械触发器写入存在事实并广播 FACT_CHANGED（任务归约入口）
            record = session.world_facts["records"]["scene:苏州·烟雨渡.exists@world"]
            self.assertEqual(record["value"], True)
            self.assertEqual(record["status"], "verified")
            fact_keys = [e.get("fact_key") for e in session.events if e.type == FACT_CHANGED]
            self.assertIn("scene:苏州·烟雨渡.exists@world", fact_keys)
            # 再次采用（草稿操作重复登记，状态一致）不再发事件
            results = session.apply_mutations([{"类型": "场景-采用草稿"}])
            self.assertTrue(all(r["ok"] for r in results), results)
            self.assertEqual(
                len([e for e in session.events if e.type == SCENE_REGISTERED]), 1)


if __name__ == "__main__":
    unittest.main()
