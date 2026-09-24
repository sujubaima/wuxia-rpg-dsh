#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene-prepare 预校验、阶段门禁与非权威写入。"""
import sys
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import engine  # noqa: E402
from store import turn_state  # noqa: E402


class ScenePrepareTest(unittest.TestCase):
    def setUp(self):
        draft = patch("engine._scene_drafts.read_draft", return_value={
            "round": None, "operations": [],
        })
        draft.start()
        self.addCleanup(draft.stop)

    def _state(self, state=turn_state.AWAITING_JUDGE):
        return patch("engine._turn_state.read_state", return_value={"state": state}), \
            patch("engine.sm.read_round", return_value=7), \
            patch("engine._workspace.pending_exists", return_value=True), \
            patch("engine._workspace.slot_view", side_effect=lambda view: nullcontext())

    def test_register_and_reconnect_are_normalized_and_written_once(self):
        state, round_number, pending, view = self._state()
        with state, round_number, pending, view, \
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
        state, round_number, pending, view = self._state()
        with state, round_number, pending, view, \
             patch("engine.sc.register_scene", return_value={"ok": False, "msg": "方位冲突"}), \
             patch("engine._scene_drafts.write_batch") as write_batch:
            result = engine.scene_prepare({
                "槽位": 1,
                "场景": [{"操作": "登记", "区域": "苏州", "场景": "废园"}],
            })
        self.assertFalse(result["ok"])
        self.assertIn("方位冲突", result["错误"])
        write_batch.assert_not_called()

    def test_empty_batch_and_wrong_phase_are_rejected(self):
        state, round_number, pending, view = self._state()
        with state, round_number, pending, view, patch("engine._scene_drafts.write_batch") as write_batch:
            result = engine.scene_prepare({"槽位": 1, "场景": []})
        self.assertFalse(result["ok"])
        self.assertIn("非空数组", result["错误"])
        write_batch.assert_not_called()

        state, round_number, pending, view = self._state(turn_state.READY)
        with state, round_number, pending, view, patch("engine._scene_drafts.write_batch") as write_batch:
            result = engine.scene_prepare({"槽位": 1, "场景": []})
        self.assertEqual(result["状态冲突"], "scene_prepare_not_expected")
        write_batch.assert_not_called()

    def test_successful_batch_is_locked_for_the_round(self):
        state, round_number, pending, view = self._state()
        with state, round_number, pending, view, \
             patch("engine._scene_drafts.read_draft", return_value={
                 "round": 7, "operations": [{"类型": "登记场景"}],
             }), patch("engine._scene_drafts.write_batch") as write_batch:
            result = engine.scene_prepare({
                "槽位": 1,
                "场景": [{"操作": "登记", "区域": "苏州", "场景": "废园"}],
            })
        self.assertFalse(result["ok"])
        self.assertEqual(result["状态冲突"], "scene_prepare_already_completed")
        write_batch.assert_not_called()

    def test_strict_item_fields_and_reconnect_requires_exits(self):
        state, round_number, pending, view = self._state()
        with state, round_number, pending, view:
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
        proposal = {"round": 7, "payload": {
            "行为": [], "当前剧情": "测试",
            "场景要素": [{"主体": "四周", "描写": "一切如常"}], "提及地点": []}}
        return patch.multiple(
            "engine.sm", _slot_writable=lambda slot: True, read_round=lambda slot: 7,
            rounds_until_save=lambda slot: 3,
        ), patch("engine._turn_state.read_state", return_value=turn), \
            patch("engine._workspace.pending_exists", return_value=True), \
            patch("engine._workspace.slot_view", side_effect=lambda view: nullcontext()), \
            patch("engine._workspace.pending_trial", side_effect=lambda slot: nullcontext(
                SimpleNamespace(commit=lambda: None))), \
            patch("engine._workspace.publish_pending"), \
            patch("engine._plot_drafts.read_draft", return_value=proposal), \
            patch("engine._plot_drafts.clear_draft"), \
            patch("engine._scene_drafts.read_draft", return_value={"operations": operations})

    def test_nonempty_draft_is_adopted_automatically(self):
        contexts = self._patch([{"类型": "登记场景"}])
        with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], \
             contexts[5], contexts[6], contexts[7], contexts[8], \
             patch("engine._settle_judge", return_value={"界面": "exploration-ui"}) as settle, \
             patch("engine._scene_drafts.clear_round") as clear_round, \
             patch("engine._quest_drafts.clear_round"), \
             patch("engine._turn_state.reset_state", return_value={"state": turn_state.READY}):
            result = engine.judge(1, {"槽位": 1})
        self.assertEqual(result["turn_state"], turn_state.READY)
        self.assertEqual(settle.call_args.args[1], [{"类型": "场景-采用草稿"}])
        clear_round.assert_called_once_with(1, 7)

    def test_empty_draft_does_not_add_adoption(self):
        contexts = self._patch([])
        with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], \
             contexts[5], contexts[6], contexts[7], contexts[8], \
             patch("engine._settle_judge", return_value={"界面": "exploration-ui"}) as settle, \
             patch("engine._quest_drafts.clear_round"), \
             patch("engine._scene_drafts.clear_round"), \
             patch("engine._turn_state.reset_state", return_value={"state": turn_state.READY}):
            engine.judge(1, {"槽位": 1})
        self.assertEqual(settle.call_args.args[1], [])

    def test_direct_scene_mutations_are_rejected_by_plot_writing(self):
        with patch("engine._workspace.pending_exists", return_value=True), \
             patch("engine._workspace.slot_view", side_effect=lambda view: nullcontext()), \
             patch("engine._turn_state.read_state", return_value={
                 "state": turn_state.AWAITING_PLOT, "origin": "普通行动",
             }), patch("engine.sm._slot_writable", return_value=True):
            result = engine.plot_writing(1, {
                "行为": [{"类型": "登记场景", "区域": "苏州", "场景": "废园"}],
                "当前剧情": "测试", "提及地点": [],
                "场景要素": [{"主体": "四周", "描写": "一切如常"}],
            })
        self.assertIn("scene-prepare", result["错误"])

    def test_failed_judge_preserves_scene_draft(self):
        contexts = self._patch([{"类型": "登记场景"}])
        with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], \
             contexts[5], contexts[6], contexts[7], contexts[8], \
             patch("engine._settle_judge", return_value={"错误": "失败"}) as settle, \
             patch("engine._scene_drafts.clear_round") as clear_round:
            result = engine.judge(1, {"槽位": 1})
        self.assertEqual(result["错误"], "失败")
        self.assertEqual(settle.call_args.args[1], [{"类型": "场景-采用草稿"}])
        clear_round.assert_not_called()


if __name__ == "__main__":
    unittest.main()
