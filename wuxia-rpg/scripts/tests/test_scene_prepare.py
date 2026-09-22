#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene-prepare 预校验、阶段门禁与非权威写入。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import engine  # noqa: E402
from store import turn_state  # noqa: E402


class ScenePrepareTest(unittest.TestCase):
    def _state(self, state=turn_state.AWAITING_JUDGE):
        return patch("engine._turn_state.read_state", return_value={"state": state}), \
            patch("engine.sm.read_round", return_value=7)

    def test_register_and_reconnect_are_normalized_and_written_once(self):
        state, round_number = self._state()
        with state, round_number, \
             patch("engine.sc.register_scene", return_value={"ok": True, "剩余配额": 3}) as register, \
             patch("engine.sc.isolate_scene", return_value={"ok": True}) as isolate, \
             patch("engine._scene_drafts.write_batch") as write_batch:
            result = engine.scene_prepare({
                "槽位": 1,
                "场景": [
                    {"操作": "登记", "区域": "苏州", "场景": "废园",
                     "方位出口": {"东": "平江路"}},
                    {"操作": "重连", "区域": "苏州", "场景": "山道",
                     "方位出口": {"北": "虎丘"}},
                ],
            })
        self.assertTrue(result["ok"], result)
        self.assertEqual(register.call_count, 2)
        isolate.assert_called_once()
        operations = write_batch.call_args.args[2]
        self.assertEqual([item["类型"] for item in operations],
                         ["登记场景", "隔离地点", "登记场景"])
        self.assertEqual(result["剩余配额"], 3)

    def test_failed_validation_does_not_replace_draft(self):
        state, round_number = self._state()
        with state, round_number, \
             patch("engine.sc.register_scene", return_value={"ok": False, "msg": "方位冲突"}), \
             patch("engine._scene_drafts.write_batch") as write_batch:
            result = engine.scene_prepare({
                "槽位": 1,
                "场景": [{"操作": "登记", "区域": "苏州", "场景": "废园"}],
            })
        self.assertFalse(result["ok"])
        self.assertIn("方位冲突", result["错误"])
        write_batch.assert_not_called()

    def test_empty_batch_clears_and_wrong_phase_is_rejected(self):
        state, round_number = self._state()
        with state, round_number, patch("engine._scene_drafts.write_batch") as write_batch:
            result = engine.scene_prepare({"槽位": 1, "场景": []})
        self.assertTrue(result["已清除"])
        write_batch.assert_called_once_with(1, 7, [])

        state, round_number = self._state(turn_state.READY)
        with state, round_number, patch("engine._scene_drafts.write_batch") as write_batch:
            result = engine.scene_prepare({"槽位": 1, "场景": []})
        self.assertEqual(result["状态冲突"], "scene_prepare_not_expected")
        write_batch.assert_not_called()

    def test_strict_item_fields_and_reconnect_requires_exits(self):
        state, round_number = self._state()
        with state, round_number:
            result = engine.scene_prepare({
                "槽位": 1,
                "场景": [{"操作": "登记", "区域": "苏州", "场景": "废园", "多余": 1}],
            })
            self.assertIn("非预期字段", result["错误"])
            result = engine.scene_prepare({
                "槽位": 1,
                "场景": [{"操作": "重连", "区域": "苏州", "场景": "废园"}],
            })
            self.assertIn("非空 方位出口", result["错误"])


class SceneDraftJudgeGateTest(unittest.TestCase):
    def _patch(self, operations):
        turn = {"state": turn_state.AWAITING_JUDGE, "origin": "普通行动"}
        return patch.multiple(
            "engine.sm", _slot_writable=lambda slot: True, read_round=lambda slot: 7,
            rounds_until_save=lambda slot: 3,
        ), patch("engine._turn_state.read_state", return_value=turn), \
            patch("engine._scene_drafts.read_draft", return_value={"operations": operations})

    def test_draft_must_be_adopted_and_empty_draft_cannot_be_adopted(self):
        storage, state, draft = self._patch([{"类型": "登记场景"}])
        with storage, state, draft:
            result = engine.judge(1, {"行为": [], "当前剧情": "测试", "提及地点": []})
        self.assertIn("未采纳", result["错误"])

        storage, state, draft = self._patch([])
        with storage, state, draft:
            result = engine.judge(1, {
                "行为": [{"类型": "场景-采用草稿"}], "当前剧情": "测试", "提及地点": [],
            })
        self.assertIn("没有可采用", result["错误"])

    def test_direct_scene_mutations_are_rejected(self):
        storage, state, draft = self._patch([])
        with storage, state, draft:
            result = engine.judge(1, {
                "行为": [{"类型": "登记场景", "区域": "苏州", "场景": "废园"}],
                "当前剧情": "测试", "提及地点": [],
            })
        self.assertIn("scene-prepare", result["错误"])

    def test_success_clears_scene_draft_but_failure_preserves_it(self):
        storage, state, draft = self._patch([{"类型": "登记场景"}])
        with storage, state, draft, \
             patch("engine._settle_judge", return_value={"界面": "exploration-ui"}), \
             patch("engine._scene_drafts.clear_round") as clear_round, \
             patch("engine._quest_drafts.clear_round"), \
             patch("engine._turn_state.reset_state", return_value={"state": turn_state.READY}):
            result = engine.judge(1, {
                "行为": [{"类型": "场景-采用草稿"}], "当前剧情": "测试", "提及地点": [],
            })
        self.assertEqual(result["turn_state"], turn_state.READY)
        clear_round.assert_called_once_with(1, 7)

        storage, state, draft = self._patch([{"类型": "登记场景"}])
        with storage, state, draft, \
             patch("engine._settle_judge", return_value={"错误": "失败"}), \
             patch("engine._scene_drafts.clear_round") as clear_round:
            result = engine.judge(1, {
                "行为": [{"类型": "场景-采用草稿"}], "当前剧情": "测试", "提及地点": [],
            })
        self.assertEqual(result["错误"], "失败")
        clear_round.assert_not_called()


if __name__ == "__main__":
    unittest.main()
