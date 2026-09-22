#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""即兴任务增量扩展：一级后继约束（创建/扩展）与扩展点强制关闭。"""
import copy
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from quest.engine import (close_extension_node, create_quest, extend_quest,  # noqa: E402
                          pending_extension_gates, validate_close_extension)
from quest.models import empty_quest_state  # noqa: E402
from quest.world_facts import empty_world_facts, register_definition, upsert_fact  # noqa: E402


FACT = "item:inc-ledger.authenticity@world"


def _facts():
    world_facts = empty_world_facts()
    register_definition(world_facts, {
        "事实键": FACT, "描述": "账册真伪", "值类型": "enum",
        "可选值": ["authentic", "forged", "uncertain"]})
    return world_facts


def _one_level_blueprint(name="增量账册", extra_node=None):
    """合规一级蓝图：初始节点 + 三个一级后继（两终局一扩展点）。"""
    nodes = [
        {"节点ID": "heard", "关闭条件": None, "关闭描述": None, "完成条件": {},
         "完成摘要": "得到账册线索。", "后继节点": ["authentic", "forged", "follow-up"]},
        {"节点ID": "authentic", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
         "完成条件": {"fact": FACT, "eq": "authentic"}, "完成摘要": "确认账册为真。", "终局": True},
        {"节点ID": "forged", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
         "完成条件": {"fact": FACT, "eq": "forged"}, "完成摘要": "确认账册为伪。", "终局": True},
        {"节点ID": "follow-up", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
         "完成条件": {"fact": FACT, "eq": "uncertain"}, "完成摘要": "证据不足，须再查。",
         "扩展点": True},
    ]
    if extra_node:
        nodes.append(extra_node)
    return {
        "版本": 1, "名称": name, "引子": "旧账册来历不明。", "隐藏目标": "查清账册真伪",
        "事实定义": [
            {"事实键": FACT, "描述": "账册真伪", "值类型": "enum",
             "可选值": ["authentic", "forged", "uncertain"]},
        ],
        "起始节点": ["heard"], "节点": nodes,
    }


def _create(world_facts=None, quest_state=None, blueprint=None):
    world_facts = world_facts if world_facts is not None else _facts()
    quest_state = quest_state if quest_state is not None else empty_quest_state()
    raw = blueprint if blueprint is not None else _one_level_blueprint()
    return world_facts, quest_state, create_quest(
        world_facts, quest_state, raw, incremental=True)


class IncrementalCreationTest(unittest.TestCase):
    def test_valid_one_level_creation_passes(self):
        world_facts, quest_state, definition = _create()
        self.assertEqual(set(definition["nodes"]),
                         {"heard", "authentic", "forged", "follow-up"})

    def test_preset_style_full_dag_unrestricted_without_flag(self):
        """非增量路径（预设加载）不受一级约束。"""
        deep = _one_level_blueprint()
        deep["节点"][3]["后继节点"] = ["deep-end"]
        deep["节点"].append(
            {"节点ID": "deep-end", "关闭条件": None, "关闭描述": None,
             "前置节点": ["follow-up"], "完成条件": {}, "终局": True})
        world_facts = _facts()
        quest_state = empty_quest_state()
        definition = create_quest(world_facts, quest_state, deep)
        self.assertIn("deep-end", definition["nodes"])

    def test_two_start_nodes_rejected(self):
        raw = _one_level_blueprint()
        raw["起始节点"] = ["heard", "authentic"]
        with self.assertRaisesRegex(ValueError, "须且只须提供一个初始节点"):
            create_quest(_facts(), empty_quest_state(), raw, incremental=True)

    def test_second_level_chain_rejected(self):
        raw = _one_level_blueprint(extra_node={
            "节点ID": "deep-end", "关闭条件": None, "关闭描述": None,
            "前置节点": ["follow-up"], "完成条件": {}, "终局": True})
        with self.assertRaisesRegex(ValueError, "前置节点须且仅须为初始节点"):
            create_quest(_facts(), empty_quest_state(), raw, incremental=True)

    def test_level_one_with_next_rejected(self):
        raw = _one_level_blueprint()
        raw["节点"][3]["后继节点"] = ["deep-end"]
        raw["节点"].append(
            {"节点ID": "deep-end", "关闭条件": None, "关闭描述": None,
             "前置节点": ["follow-up"], "完成条件": {}, "终局": True})
        with self.assertRaisesRegex(ValueError, "不得带后继节点"):
            create_quest(_facts(), empty_quest_state(), raw, incremental=True)

    def test_entry_successor_mismatch_rejected(self):
        raw = _one_level_blueprint()
        raw["节点"][0]["后继节点"] = ["authentic", "forged", "follow-up", "ghost"]
        with self.assertRaisesRegex(ValueError, "后继节点须且仅须为一级后继"):
            create_quest(_facts(), empty_quest_state(), raw, incremental=True)

    def test_entry_as_extension_rejected(self):
        raw = _one_level_blueprint()
        raw["节点"][0]["扩展点"] = True
        with self.assertRaisesRegex(ValueError, "初始节点.*不得为终局或扩展点"):
            create_quest(_facts(), empty_quest_state(), raw, incremental=True)


class IncrementalExtensionTest(unittest.TestCase):
    def _prepared(self, fact_value="uncertain"):
        world_facts, quest_state, definition = _create()
        upsert_fact(world_facts, FACT, fact_value)
        return world_facts, quest_state, definition

    def test_valid_one_level_multi_branch_extension(self):
        world_facts, quest_state, definition = self._prepared()
        second_fact = "item:inc-seal.origin@world"
        extended = extend_quest(world_facts, quest_state, {
            "名称": definition["name"], "扩展点": "follow-up", "版本": 2,
            "起始节点": ["trace-seal", "ask-witness"],
            "事实定义": [{"事实键": second_fact, "描述": "印章来路", "值类型": "enum",
                        "可选值": ["official", "forged"]}],
            "节点": [
                {"节点ID": "trace-seal", "关闭条件": None, "关闭描述": None,
                 "前置节点": ["follow-up"],
                 "完成条件": {"fact": second_fact, "eq": "official"},
                 "完成摘要": "查到印鉴出自官府。", "终局": True},
                {"节点ID": "ask-witness", "关闭条件": None, "关闭描述": None,
                 "前置节点": ["follow-up"],
                 "完成条件": {"fact": second_fact, "eq": "forged"},
                 "完成摘要": "证人供出伪造。", "扩展点": True},
            ],
        }, incremental=True)
        self.assertEqual(set(extended["nodes"]["follow-up"]["next"]),
                         {"trace-seal", "ask-witness"})

    def test_extension_requires_extension_point_only(self):
        world_facts, quest_state, definition = self._prepared()
        second_fact = "item:inc-seal.origin@world"
        with self.assertRaisesRegex(ValueError, "前置节点须且仅须为扩展点"):
            extend_quest(world_facts, quest_state, {
                "名称": definition["name"], "扩展点": "follow-up", "版本": 2,
                "起始节点": ["stray"],
                "节点": [
                    {"节点ID": "stray", "关闭条件": None, "关闭描述": None,
                     "前置节点": ["authentic"], "完成条件": {}, "终局": True},
                ],
            }, incremental=True)

    def test_extension_node_with_next_rejected(self):
        world_facts, quest_state, definition = self._prepared()
        with self.assertRaisesRegex(ValueError, "不得带后继节点"):
            extend_quest(world_facts, quest_state, {
                "名称": definition["name"], "扩展点": "follow-up", "版本": 2,
                "起始节点": ["trace-seal"],
                "节点": [
                    {"节点ID": "trace-seal", "关闭条件": None, "关闭描述": None,
                     "前置节点": ["follow-up"], "完成条件": {}, "后继节点": ["deep-end"]},
                    {"节点ID": "deep-end", "关闭条件": None, "关闭描述": None,
                     "前置节点": ["trace-seal"], "完成条件": {}, "终局": True},
                ],
            }, incremental=True)

    def test_preset_style_extension_unrestricted_without_flag(self):
        world_facts, quest_state, definition = self._prepared()
        extended = extend_quest(world_facts, quest_state, {
            "名称": definition["name"], "扩展点": "follow-up", "版本": 2,
            "起始节点": ["trace-seal"],
            "节点": [
                {"节点ID": "trace-seal", "关闭条件": None, "关闭描述": None,
                 "前置节点": ["follow-up"], "完成条件": {}, "后继节点": ["deep-end"]},
                {"节点ID": "deep-end", "关闭条件": None, "关闭描述": None,
                 "前置节点": ["trace-seal"], "完成条件": {}, "终局": True},
            ],
        })
        self.assertIn("deep-end", extended["nodes"])


class CloseExtensionTest(unittest.TestCase):
    def _bud_blueprint(self):
        """最小生长芽蓝图：入口 + 单扩展点（关闭后全路径落定即自动收尾）。"""
        return {
            "版本": 1, "名称": "增量账册", "引子": "旧账册来历不明。", "隐藏目标": "查清账册真伪",
            "事实定义": [
                {"事实键": FACT, "描述": "账册真伪", "值类型": "enum",
                 "可选值": ["authentic", "forged", "uncertain"]},
            ],
            "起始节点": ["heard"],
            "节点": [
                {"节点ID": "heard", "关闭条件": None, "关闭描述": None, "完成条件": {},
                 "完成摘要": "得到账册线索。", "后继节点": ["follow-up"]},
                {"节点ID": "follow-up", "关闭条件": None, "关闭描述": None,
                 "前置节点": ["heard"],
                 "完成条件": {"fact": FACT, "eq": "uncertain"}, "完成摘要": "证据不足，须再查。",
                 "扩展点": True},
            ],
        }

    def _reached_bud(self):
        """建线并把入口走到扩展点前沿：heard 完成，follow-up 条件已真。"""
        world_facts = _facts()
        quest_state = empty_quest_state()
        definition = create_quest(world_facts, quest_state, self._bud_blueprint(),
                                  incremental=True)
        upsert_fact(world_facts, FACT, "uncertain")
        from quest.engine import reduce_affected_quests
        reduce_affected_quests(world_facts, quest_state)
        self.assertEqual(quest_state["runtimes"]["增量账册"]["completed_node_ids"], ["heard"])
        self.assertEqual(pending_extension_gates(world_facts, quest_state),
                         [("增量账册", "follow-up")])
        return world_facts, quest_state, definition

    def test_close_extension_writes_summary_and_ends_quest(self):
        world_facts, quest_state, definition = self._reached_bud()
        before_version = definition["version"]
        notice = close_extension_node(quest_state, "增量账册", "follow-up",
                                      "此案无从再查，就此搁下。")
        runtime = quest_state["runtimes"]["增量账册"]
        self.assertIn("follow-up", runtime["closed_node_ids"])
        self.assertEqual(definition["nodes"]["follow-up"]["close_summary"],
                         "此案无从再查，就此搁下。")
        self.assertEqual(definition["version"], before_version + 1)
        self.assertEqual(notice["node_state"], "closed")
        # 关闭后 gate 不再打回；全部路径落定触发自动收尾
        self.assertEqual(pending_extension_gates(world_facts, quest_state), [])
        from quest.engine import reduce_affected_quests
        reduce_affected_quests(world_facts, quest_state)
        self.assertEqual(runtime["lifecycle"], "ended")

    def test_close_requires_non_empty_summary(self):
        world_facts, quest_state, _ = self._reached_bud()
        with self.assertRaisesRegex(ValueError, "须提供非空 描述"):
            close_extension_node(quest_state, "增量账册", "follow-up", "  ")

    def test_close_validations(self):
        world_facts, quest_state, definition = self._reached_bud()
        with self.assertRaisesRegex(ValueError, "节点不存在"):
            validate_close_extension(quest_state, "增量账册", "nope")
        with self.assertRaisesRegex(ValueError, "不是扩展点"):
            validate_close_extension(quest_state, "增量账册", "heard")
        with self.assertRaisesRegex(ValueError, "未知任务"):
            validate_close_extension(quest_state, "没这条线", "follow-up")

    def test_close_rejected_after_activation(self):
        world_facts, quest_state, definition = self._reached_bud()
        extend_quest(world_facts, quest_state, {
            "名称": "增量账册", "扩展点": "follow-up", "版本": 2,
            "起始节点": ["trace-seal"],
            "节点": [
                {"节点ID": "trace-seal", "关闭条件": None, "关闭描述": None,
                 "前置节点": ["follow-up"], "完成条件": {}, "终局": True},
            ],
        }, incremental=True)
        with self.assertRaisesRegex(ValueError, "已激活"):
            close_extension_node(quest_state, "增量账册", "follow-up", "已无必要。")

    def test_close_rejected_twice(self):
        world_facts, quest_state, definition = self._reached_bud()
        close_extension_node(quest_state, "增量账册", "follow-up", "此路已断。")
        with self.assertRaisesRegex(ValueError, "已关闭或阻断"):
            close_extension_node(quest_state, "增量账册", "follow-up", "再关一次。")

    def test_close_hidden_quest_rejected(self):
        world_facts = _facts()
        quest_state = empty_quest_state()
        create_quest(world_facts, quest_state, _one_level_blueprint(), hidden=True,
                     incremental=True)
        with self.assertRaisesRegex(ValueError, "不在进行中"):
            close_extension_node(quest_state, "增量账册", "follow-up", "还没开始就结束。")


if __name__ == "__main__":
    unittest.main()
