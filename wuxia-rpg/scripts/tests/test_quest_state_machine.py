#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务蓝图校验、分支归约、奖励防重与扩展约束。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from settle.quest_conditions import validate_condition
from settle.quest_engine import (create_quest, discover_quest, extend_quest,
                                 reduce_affected_quests)
from settle.quest_models import empty_quest_state
from settle.quest_projection import project_clues
from settle.quest_validator import validate_quest_definition
from settle.quest_models import normalize_quest_definition
from settle.world_facts import empty_world_facts, register_definition, upsert_fact


FACT = "item:ledger_001.authenticity@world"
SEAL_FACT = "item:ledger_001.seal@world"


def ledger_blueprint(include_forged=True):
    nodes = [
        {
            "节点ID": "heard", "完成条件": {}, "完成摘要": "得知账册之谜。",
            "后继节点": ["authentic"] + (["forged"] if include_forged else []),
        },
        {
            "节点ID": "authentic", "前置节点": ["heard"],
            "完成条件": {"fact": FACT, "eq": "authentic"},
            "完成摘要": "确认账册是真品。", "终局": "解决",
        },
    ]
    if include_forged:
        nodes.append({
            "节点ID": "forged", "前置节点": ["heard"],
            "完成条件": {"fact": FACT, "eq": "forged"},
            "完成摘要": "查明账册系伪造。", "终局": "关闭",
            "奖励": {
                "奖励ID": "ledger:forged:reward",
                "描述": "经验500",
                "状态变更": [{"类型": "经验", "操作": "加", "角色": "玩家", "值": 500}],
            },
        })
    return {
        "任务ID": "ledger-case", "名称": "账册疑云", "引子": "一册旧账牵出疑云。",
        "隐藏目标": "确认账册真伪", "起始节点": ["heard"], "节点": nodes,
    }


class QuestStateMachineTest(unittest.TestCase):
    def setUp(self):
        self.facts = empty_world_facts()
        register_definition(self.facts, {
            "事实键": FACT, "值类型": "enum", "可选值": ["authentic", "forged"],
        })
        register_definition(self.facts, {
            "事实键": SEAL_FACT, "值类型": "enum", "可选值": ["intact", "broken"],
        })
        self.quests = empty_quest_state()

    def test_unknown_enum_requires_an_exit_for_every_value(self):
        definition = normalize_quest_definition(ledger_blueprint(include_forged=False))
        with self.assertRaisesRegex(ValueError, "未覆盖事实"):
            validate_quest_definition(definition, self.facts, self.quests)

    def test_fact_completes_only_matching_branch_and_claims_reward_once(self):
        create_quest(self.facts, self.quests, ledger_blueprint())
        mutations, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, quest_id="ledger-case"
        )
        self.assertEqual(mutations, [])
        self.assertEqual([n["node_id"] for n in notices], ["heard"])

        upsert_fact(self.facts, FACT, "forged")
        mutations, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, fact_key=FACT
        )
        runtime = self.quests["runtimes"]["ledger-case"]
        self.assertEqual(runtime["lifecycle"], "closed")
        self.assertEqual(runtime["completed_node_ids"], ["heard", "forged"])
        self.assertEqual(len(mutations), 1)
        self.assertEqual(notices[-1]["summary"], "查明账册系伪造。")

        mutations, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, fact_key=FACT
        )
        self.assertEqual(mutations, [])
        self.assertEqual(notices, [])
        self.assertEqual(runtime["claimed_reward_ids"], ["ledger:forged:reward"])

    def test_verified_conflict_rejects_new_blueprint_without_exit(self):
        upsert_fact(self.facts, FACT, "forged")
        definition = normalize_quest_definition(ledger_blueprint(include_forged=False))
        with self.assertRaisesRegex(ValueError, "已无可达终局"):
            validate_quest_definition(definition, self.facts, self.quests)

    def test_all_join_cannot_depend_on_mutually_exclusive_enum_branches(self):
        raw = {
            "任务ID": "impossible-join", "名称": "不可能的汇合",
            "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "后继节点": ["authentic", "forged"]},
                {"节点ID": "authentic", "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "authentic"},
                 "后继节点": ["finish"]},
                {"节点ID": "forged", "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "forged"},
                 "后继节点": ["finish"]},
                {"节点ID": "finish", "前置节点": ["authentic", "forged"],
                 "汇合规则": "all", "终局": "关闭"},
            ],
        }
        definition = normalize_quest_definition(raw)
        with self.assertRaisesRegex(ValueError, "事实枚举组合"):
            validate_quest_definition(definition, self.facts, self.quests)

    def test_enum_coverage_checks_cartesian_combinations(self):
        def outcome(node_id, authenticity, seal):
            return {
                "节点ID": node_id, "前置节点": ["start"],
                "完成条件": {"all": [
                    {"fact": FACT, "eq": authenticity},
                    {"fact": SEAL_FACT, "eq": seal},
                ]},
                "终局": "关闭",
            }

        raw = {
            "任务ID": "ledger-seal", "名称": "账册与封印",
            "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "后继节点": ["auth-intact", "auth-broken", "forged-intact"]},
                outcome("auth-intact", "authentic", "intact"),
                outcome("auth-broken", "authentic", "broken"),
                outcome("forged-intact", "forged", "intact"),
            ],
        }
        definition = normalize_quest_definition(raw)
        with self.assertRaisesRegex(ValueError, "authenticity@world=forged.*seal@world=broken"):
            validate_quest_definition(definition, self.facts, self.quests)

    def test_hidden_quest_waits_for_discovery_before_reduction(self):
        create_quest(self.facts, self.quests, ledger_blueprint(), hidden=True)
        _, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, quest_id="ledger-case"
        )
        self.assertEqual(notices, [])
        self.assertEqual(
            self.quests["runtimes"]["ledger-case"]["completed_node_ids"], []
        )
        discover_quest(self.quests, "ledger-case")
        _, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, quest_id="ledger-case"
        )
        self.assertEqual([item["node_id"] for item in notices], ["heard"])

    def test_extension_must_activate_an_explicit_extension_point(self):
        raw = {
            "任务ID": "ledger-extension", "名称": "账册余波",
            "起始节点": ["heard"],
            "节点": [
                {"节点ID": "heard", "完成条件": {}, "完成摘要": "得知余波。",
                 "后继节点": ["authentic", "future"]},
                {"节点ID": "authentic", "前置节点": ["heard"],
                 "完成条件": {"fact": FACT, "eq": "authentic"},
                 "完成摘要": "真账已有定论。", "终局": "解决"},
                {"节点ID": "future", "前置节点": ["heard"],
                 "完成条件": {"fact": FACT, "eq": "forged"},
                 "完成摘要": "伪账牵出新的方向。", "扩展点": True},
            ],
        }
        create_quest(self.facts, self.quests, raw)
        with self.assertRaisesRegex(ValueError, "须指定 扩展点"):
            extend_quest(self.facts, self.quests, {
                "任务ID": "ledger-extension", "版本": 2,
                "起始节点": ["forged-end"],
                "节点": [{"节点ID": "forged-end", "终局": "关闭"}],
            })
        extended = extend_quest(self.facts, self.quests, {
            "任务ID": "ledger-extension", "扩展点": "future", "版本": 2,
            "起始节点": ["forged-end"],
            "节点": [{"节点ID": "forged-end", "前置节点": ["future"],
                       "完成摘要": "伪账后续已收束。", "终局": "关闭"}],
        })
        self.assertEqual(extended["nodes"]["future"]["next"], ["forged-end"])
        self.assertFalse(extended["nodes"]["future"]["extension"])

    def test_condition_dsl_rejects_unknown_and_mistyped_fields(self):
        with self.assertRaisesRegex(ValueError, "未知字段"):
            validate_condition({"fact": FACT, "eq": "forged", "阶段": "done"})
        with self.assertRaisesRegex(ValueError, "exists 须为 bool"):
            validate_condition({"fact": FACT, "exists": "yes"})
        with self.assertRaisesRegex(ValueError, "completed 须为 bool"):
            validate_condition({"node": "heard", "completed": 1})

    def test_projection_uses_completion_order_not_blueprint_order(self):
        definition = normalize_quest_definition(ledger_blueprint())
        self.quests["definitions"]["ledger-case"] = definition
        self.quests["runtimes"]["ledger-case"] = {
            "lifecycle": "active", "completed_node_ids": ["forged", "heard"]
        }
        projected = project_clues(self.quests)
        self.assertEqual(
            [item["描述"] for item in projected[0]["进展节点"]],
            ["查明账册系伪造。", "得知账册之谜。"],
        )

    def test_duplicate_quest_id_is_rejected(self):
        create_quest(self.facts, self.quests, ledger_blueprint())
        with self.assertRaisesRegex(ValueError, "已存在"):
            create_quest(self.facts, self.quests, ledger_blueprint())


if __name__ == "__main__":
    unittest.main()
