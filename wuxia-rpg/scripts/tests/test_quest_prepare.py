#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quest-prepare 预校验、阶段门禁与非权威写入。"""
import copy
from contextlib import ExitStack, contextmanager, nullcontext
from types import SimpleNamespace
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import engine  # noqa: E402
from quest.engine import create_quest  # noqa: E402
from quest.models import empty_quest_state  # noqa: E402
from quest.world_facts import empty_world_facts, register_definition, upsert_fact  # noqa: E402
from store import turn_state  # noqa: E402


FACT = "item:prepared-ledger.authenticity@world"


def blueprint(fact=FACT, name="备好的账册"):
    return {
        "版本": 1,
        "名称": name,
        "引子": "旧账册来历不明。",
        "隐藏目标": "查清账册真伪",
        "事实定义": [
            {"事实键": fact, "描述": "账册的真实真伪", "值类型": "enum", "可选值": ["authentic", "forged", "uncertain"]},
        ],
        "起始节点": ["heard"],
        "节点": [
            {"节点ID": "heard", "关闭条件": None, "关闭描述": None, "完成条件": {}, "完成摘要": "得到账册线索。",
             "后继节点": ["authentic", "forged", "follow-up"]},
            {"节点ID": "authentic", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
             "完成条件": {"fact": fact, "eq": "authentic"},
             "完成摘要": "确认账册为真。", "终局": True},
            {"节点ID": "forged", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
             "完成条件": {"fact": fact, "eq": "forged"},
             "完成摘要": "确认账册为伪。", "终局": True},
            {"节点ID": "follow-up", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
             "完成条件": {"fact": fact, "eq": "uncertain"}, "完成摘要": "证据不足，须再查。",
             "扩展点": True},
        ],
    }


def dependent_blueprint(fact, name):
    return {
        "版本": 1, "名称": name, "引子": "追查新线索。", "隐藏目标": "核实地点",
        "起始节点": ["start"],
        "节点": [
            {"节点ID": "start", "关闭条件": None, "关闭描述": None,
             "完成条件": {}, "完成摘要": "开始追查。", "后继节点": ["done"]},
            {"节点ID": "done", "关闭条件": None, "关闭描述": None,
             "前置节点": ["start"], "完成条件": {"fact": fact, "eq": True},
             "完成摘要": "地点已确认。", "终局": True},
        ],
    }


class PendingPrepareCase(unittest.TestCase):
    def setUp(self):
        pending = patch("engine._workspace.pending_exists", return_value=True)
        view = patch("engine._workspace.slot_view", side_effect=lambda name: nullcontext())
        drafts = patch("engine._quest_drafts.read_drafts", return_value={
            "round": None, "order": [], "drafts": {},
        })
        pending.start()
        view.start()
        drafts.start()
        self.addCleanup(drafts.stop)
        self.addCleanup(view.stop)
        self.addCleanup(pending.stop)


class QuestPrepareTest(PendingPrepareCase):
    def _patch_engine_state(self, *, state=turn_state.AWAITING_JUDGE,
                            facts=None, quests=None, round_number=7):
        return patch.multiple(
            "engine.sm",
            read_world_facts=lambda slot: copy.deepcopy(facts or {}),
            read_quest_state=lambda slot: copy.deepcopy(quests or {}),
            read_explore=lambda slot: {"任务摘要及进度": []},
            read_round=lambda slot: round_number,
        ), patch("engine._turn_state.read_state", return_value={"state": state}), \
            patch("engine._plot_drafts.read_draft", return_value={
                "round": round_number, "payload": {"行为": []}})

    def test_batch_create_returns_task_summaries_and_writes_once(self):
        second_fact = "item:second-ledger.authenticity@world"
        payload = {
            "槽位": 1,
            "任务": [
                {"操作": "创建", "蓝图": blueprint()},
                {"操作": "创建", "蓝图": blueprint(
                    second_fact, "第二本账册"
                )},
            ],
        }
        storage, phase, plot = self._patch_engine_state()
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare(payload)
        self.assertTrue(result["ok"], result)
        self.assertEqual([row["名称"] for row in result["任务"]],
                         ["备好的账册", "第二本账册"])
        self.assertEqual(result["任务"][0]["节点数"], 4)
        self.assertEqual(result["任务"][0]["终局数"], 2)
        self.assertEqual(result["任务"][0]["关闭条件节点数"], 0)
        self.assertEqual(result["任务"][0]["引用事实"], [FACT])
        self.assertEqual(result["turn_state"], turn_state.AWAITING_JUDGE)
        write_batch.assert_called_once()
        self.assertEqual(write_batch.call_args.args[:2], (1, 7))
        records = write_batch.call_args.args[2]
        self.assertEqual([record["quest_name"] for record in records],
                         ["备好的账册", "第二本账册"])
        self.assertEqual(records[0]["payload"], blueprint())

    def test_prepare_accepts_fact_defined_by_plot_proposal(self):
        fact = "scene:proposed-ledger.discovered@world"
        definition = {"事实键": fact, "描述": "是否找到新账册", "值类型": "bool"}
        storage, phase, _plot = self._patch_engine_state()
        with storage, phase, \
             patch("engine._plot_drafts.read_draft", return_value={
                 "round": 7, "payload": {"行为": [
                     {"类型": "事实-写入", "事实": fact, "值": True, "定义": definition},
                 ]}}), \
             patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare({"槽位": 1, "任务": [
                {"操作": "创建", "蓝图": dependent_blueprint(fact, "新账册")},
            ]})
        self.assertTrue(result["ok"], result)
        write_batch.assert_called_once()

    def test_prepare_accepts_scene_fact_from_same_round_scene_draft(self):
        scene_fact = "scene:苏州·废园.exists@world"
        scene_batch = {"round": 7, "operations": [
            {"类型": "登记场景", "区域": "苏州", "场景": "废园"},
        ]}
        storage, phase, plot = self._patch_engine_state()
        with storage, phase, plot, \
             patch("engine._scene_drafts.read_draft", return_value=scene_batch), \
             patch("engine._scene_drafts.select_draft", return_value=scene_batch), \
             patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare({"槽位": 1, "任务": [
                {"操作": "创建", "蓝图": dependent_blueprint(scene_fact, "废园踪迹")},
            ]})
        self.assertTrue(result["ok"], result)
        write_batch.assert_called_once()

    def test_prepare_accepts_blueprint_conflicting_with_current_fact(self):
        facts = empty_world_facts()
        register_definition(facts, {
            "事实键": FACT, "描述": "账册的真实真伪",
            "值类型": "enum", "可选值": ["authentic", "forged", "uncertain"],
        })
        upsert_fact(facts, FACT, "forged")
        partial = blueprint()
        partial["节点"] = [partial["节点"][0], partial["节点"][1], partial["节点"][3]]
        partial["节点"][0]["后继节点"] = ["authentic", "follow-up"]
        storage, phase, plot = self._patch_engine_state(facts=facts)
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare({
                "槽位": 1, "任务": [{"操作": "创建", "蓝图": partial}],
            })
        self.assertTrue(result["ok"], result)
        write_batch.assert_called_once()

    def test_successful_prepare_is_locked_for_the_round(self):
        storage, phase, plot = self._patch_engine_state()
        with storage, phase, plot, \
             patch("engine._quest_drafts.read_drafts", return_value={
                 "round": 7, "order": ["备好的账册"], "drafts": {},
             }), patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare({
                "槽位": 1,
                "任务": [{"操作": "创建", "蓝图": blueprint(name="修正后的账册")}],
            })
        self.assertFalse(result["ok"])
        self.assertEqual(result["状态冲突"], "quest_prepare_already_completed")
        write_batch.assert_not_called()

    def test_invalid_blueprint_and_wrong_phase_do_not_write(self):
        bad = blueprint()
        bad["节点"] = bad["节点"][:1]
        storage, phase, plot = self._patch_engine_state()
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare({
                "槽位": 1, "任务": [{"操作": "创建", "蓝图": bad}],
            })
        self.assertFalse(result["ok"])
        self.assertIn("预校验失败", result["错误"])
        write_batch.assert_not_called()

        for blocked_state in (turn_state.READY, turn_state.AWAITING_BATTLE_START):
            storage, phase, plot = self._patch_engine_state(state=blocked_state)
            with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
                result = engine.quest_prepare({
                    "槽位": 1,
                    "任务": [{"操作": "创建", "蓝图": blueprint()}],
                })
            self.assertEqual(result["状态冲突"], "quest_prepare_not_expected")
            self.assertEqual(result["turn_state"], blocked_state)
            write_batch.assert_not_called()

    def test_new_fact_definition_requires_description(self):
        bad = blueprint()
        bad["事实定义"][0].pop("描述")
        storage, phase, plot = self._patch_engine_state()
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare({
                "槽位": 1, "任务": [{"操作": "创建", "蓝图": bad}],
            })
        self.assertFalse(result["ok"])
        self.assertIn("须提供非空 描述", result["错误"])
        write_batch.assert_not_called()

    def test_extension_reuses_existing_validator(self):
        facts = empty_world_facts()
        quests = empty_quest_state()
        base = {
            "版本": 1, "名称": "待续之事",
            "引子": "尚有余波。", "隐藏目标": "查清后续",
            "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None, "完成条件": {}, "完成摘要": "开始追查。",
                 "后继节点": ["done", "follow-up"]},
                {"节点ID": "done", "关闭条件": None, "关闭描述": None, "前置节点": ["start"], "完成条件": {},
                 "完成摘要": "主事已了。", "终局": True},
                {"节点ID": "follow-up", "关闭条件": None, "关闭描述": None, "前置节点": ["start"], "完成条件": {},
                 "完成摘要": "仍有后续。", "扩展点": True},
            ],
        }
        create_quest(facts, quests, base)
        extension = {
            "名称": "待续之事", "扩展点": "follow-up", "版本": 2,
            "起始节点": ["trace"],
            "节点": [
                {"节点ID": "trace", "关闭条件": None, "关闭描述": None, "前置节点": ["follow-up"], "完成条件": {},
                 "完成摘要": "查清余波。", "终局": True},
            ],
        }
        storage, phase, plot = self._patch_engine_state(facts=facts, quests=quests)
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare({
                "槽位": 1,
                "任务": [{"操作": "扩展", "蓝图": extension}],
            })
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["任务"][0]["操作"], "扩展")
        self.assertEqual(result["任务"][0]["版本"], 2)
        self.assertEqual(write_batch.call_args.args[2][0]["kind"], "extend")

    def test_batch_and_item_fields_are_strict(self):
        storage, phase, plot = self._patch_engine_state()
        with storage, phase, plot:
            result = engine.quest_prepare({"槽位": 1, "任务": [], "操作": "创建"})
            self.assertIn("非预期字段", result["错误"])
            result = engine.quest_prepare({
                "槽位": 1,
                "任务": [{"操作": "创建", "蓝图": blueprint(), "隐藏": "否"}],
            })
            self.assertIn("布尔值", result["错误"])
            result = engine.quest_prepare({
                "槽位": 1,
                "任务": [{"操作": "扩展", "蓝图": {}, "隐藏": False}],
            })
            self.assertIn("非预期字段", result["错误"])

    def test_duplicate_clue_names_reject_whole_batch(self):
        storage, phase, plot = self._patch_engine_state()
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare({
                "槽位": 1,
                "任务": [
                    {"操作": "创建", "蓝图": blueprint()},
                    {"操作": "创建", "蓝图": blueprint()},
                ],
            })
        self.assertFalse(result["ok"])
        self.assertIn("重复线索名称", result["错误"])
        write_batch.assert_not_called()

    @contextmanager
    def _staged_judge(self, settled, quest_order=None, scene_operations=None):
        turn = {"state": turn_state.AWAITING_JUDGE, "origin": "普通行动"}
        with ExitStack() as stack:
            stack.enter_context(patch("engine.sm._slot_writable", return_value=True))
            stack.enter_context(patch("engine._turn_state.read_state", return_value=turn))
            stack.enter_context(patch("engine.sm.read_round", return_value=7))
            stack.enter_context(patch("engine._workspace.pending_exists", return_value=True))
            stack.enter_context(patch("engine._workspace.slot_view", side_effect=lambda view: nullcontext()))
            stack.enter_context(patch("engine._workspace.pending_trial", side_effect=lambda slot:
                                      nullcontext(SimpleNamespace(commit=lambda: None))))
            stack.enter_context(patch("engine._workspace.publish_pending"))
            stack.enter_context(patch("engine._plot_drafts.read_draft", return_value={
                "round": 7, "payload": {"行为": [], "当前剧情": "本轮裁定测试。",
                                         "场景要素": [{"主体": "四周", "描写": "一切如常"}],
                                         "提及地点": []}}))
            stack.enter_context(patch("engine._plot_drafts.clear_draft"))
            stack.enter_context(patch("engine._scene_drafts.read_draft", return_value={
                "round": 7 if scene_operations else None,
                "operations": list(scene_operations or []),
            }))
            order = list(quest_order or [])
            stack.enter_context(patch("engine._quest_drafts.read_drafts", return_value={
                "round": 7 if order else None, "order": order, "drafts": {},
            }))
            stack.enter_context(patch("engine._scene_drafts.clear_round"))
            settle = stack.enter_context(patch("engine._settle_judge", return_value=settled))
            stack.enter_context(patch("engine._turn_state.reset_state",
                                      return_value={"state": turn_state.READY}))
            with patch("engine._quest_drafts.clear_round") as clear_round:
                yield clear_round, settle

    def test_successful_judge_clears_round_drafts_even_when_unused(self):
        with self._staged_judge({"界面": "exploration-ui"}) as (clear_round, _settle):
            result = engine.judge(1, {"槽位": 1})
        clear_round.assert_called_once_with(1, 7)
        self.assertEqual(result["turn_state"], turn_state.READY)

    def test_judge_adopts_scene_then_all_quest_drafts_in_order(self):
        with self._staged_judge(
                {"界面": "exploration-ui"},
                ["先查账册", "再访证人"],
                [{"类型": "登记场景"}],
        ) as (_clear, settle):
            result = engine.judge(1, {"槽位": 1})
        self.assertEqual(result["turn_state"], turn_state.READY)
        self.assertEqual(settle.call_args.args[1], [
            {"类型": "场景-采用草稿"},
            {"类型": "线索-采用草稿", "名称列表": ["先查账册", "再访证人"]},
        ])

    def test_failed_judge_preserves_round_drafts(self):
        with self._staged_judge({"错误": "裁定失败"}) as (clear_round, _settle):
            result = engine.judge(1, {"槽位": 1})
        clear_round.assert_not_called()
        self.assertEqual(result["错误"], "裁定失败")
        self.assertEqual(result["turn_state"], turn_state.AWAITING_JUDGE)


class QuestPrepareCloseTest(PendingPrepareCase):
    def _patch(self, facts, quests):
        return patch.multiple(
            "engine.sm",
            read_world_facts=lambda slot: copy.deepcopy(facts),
            read_quest_state=lambda slot: copy.deepcopy(quests),
            read_explore=lambda slot: {"任务摘要及进度": []},
            read_round=lambda slot: 7,
        ), patch("engine._turn_state.read_state",
                 return_value={"state": turn_state.AWAITING_JUDGE}), \
            patch("engine._plot_drafts.read_draft", return_value={
                "round": 7, "payload": {"行为": []}})

    def _created_state(self):
        facts = empty_world_facts()
        quests = empty_quest_state()
        create_quest(facts, quests, blueprint())
        return facts, quests

    def test_close_prepare_writes_close_draft(self):
        facts, quests = self._created_state()
        payload = {"槽位": 1, "任务": [{"操作": "关闭", "蓝图": {
            "名称": "备好的账册", "节点": "follow-up", "描述": "此案无从再查，就此搁下。"}}]}
        storage, phase, plot = self._patch(facts, quests)
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare(payload)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["任务"][0], {
            "操作": "关闭", "版本": 1, "线索": "备好的账册",
            "关闭节点": "follow-up", "描述": "此案无从再查，就此搁下。"})
        record = write_batch.call_args[0][2][0]
        self.assertEqual(record["kind"], "close")
        self.assertEqual(record["quest_name"], "备好的账册")
        self.assertEqual(record["definition_version"], 1)
        self.assertEqual(record["content_hash"],
                         engine._quest_drafts.definition_hash("close", record["payload"]))

    def test_close_prepare_rejects_extra_fields(self):
        facts, quests = self._created_state()
        payload = {"槽位": 1, "任务": [{"操作": "关闭", "蓝图": {
            "名称": "备好的账册", "节点": "follow-up", "描述": "断线。",
            "扩展点": "follow-up"}}]}
        storage, phase, plot = self._patch(facts, quests)
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare(payload)
        self.assertFalse(result["ok"])
        self.assertIn("仅允许 名称/节点/描述", result["错误"])
        write_batch.assert_not_called()

    def test_close_prepare_rejects_non_extension_node(self):
        facts, quests = self._created_state()
        payload = {"槽位": 1, "任务": [{"操作": "关闭", "蓝图": {
            "名称": "备好的账册", "节点": "heard", "描述": "整个线索废弃。"}}]}
        storage, phase, plot = self._patch(facts, quests)
        with storage, phase, plot, patch("engine._quest_drafts.write_batch") as write_batch:
            result = engine.quest_prepare(payload)
        self.assertFalse(result["ok"])
        self.assertIn("不是扩展点", result["错误"])
        write_batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
