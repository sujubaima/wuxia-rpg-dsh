#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务蓝图校验、分支归约、奖励防重与扩展约束。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from quest.conditions import validate_condition
from quest.engine import (create_quest, discover_quest, extend_quest,
                          pending_extension_gates, potential_progress_hints,
                          reduce_affected_quests)
from quest.events import EventFactory, LOCATION_CHANGED
from quest.models import empty_quest_state, normalize_quest_state
from quest.projection import project_clues
from quest.triggers import _mechanical_fact_mutations
from quest.validator import validate_quest_definition
from quest.models import normalize_quest_definition
from quest.world_facts import empty_world_facts, register_definition, upsert_fact


FACT = "item:ledger_001.authenticity@world"
SEAL_FACT = "item:ledger_001.seal@world"


def ledger_blueprint(include_forged=True):
    nodes = [
        {
            "节点ID": "heard", "关闭条件": None, "关闭描述": None, "完成条件": {}, "完成摘要": "得知账册之谜。",
            "后继节点": ["authentic"] + (["forged"] if include_forged else []),
        },
        {
            "节点ID": "authentic", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
            "完成条件": {"fact": FACT, "eq": "authentic"},
            "完成摘要": "确认账册是真品。", "终局": "解决",
        },
    ]
    if include_forged:
        nodes.append({
            "节点ID": "forged", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
            "完成条件": {"fact": FACT, "eq": "forged"},
            "完成摘要": "查明账册系伪造。", "终局": "关闭",
            "奖励": {
                "奖励ID": "ledger:forged:reward",
                "描述": "经验500",
                "状态变更": [{"类型": "经验", "操作": "加", "角色": "玩家", "值": 500}],
            },
        })
    return {
        "名称": "账册疑云", "引子": "一册旧账牵出疑云。",
        "隐藏目标": "确认账册真伪", "起始节点": ["heard"], "节点": nodes,
    }


class QuestStateMachineTest(unittest.TestCase):
    def setUp(self):
        self.facts = empty_world_facts()
        register_definition(self.facts, {
            "事实键": FACT, "描述": "账册的真实真伪",
            "值类型": "enum", "可选值": ["authentic", "forged"],
        })
        register_definition(self.facts, {
            "事实键": SEAL_FACT, "描述": "账册封印是否完好",
            "值类型": "enum", "可选值": ["intact", "broken"],
        })
        self.quests = empty_quest_state()

    def test_unknown_enum_does_not_require_an_exit_for_every_value(self):
        definition = normalize_quest_definition(ledger_blueprint(include_forged=False))
        self.assertTrue(validate_quest_definition(definition, self.facts, self.quests))

    def test_fact_completes_only_matching_branch_and_claims_reward_once(self):
        create_quest(self.facts, self.quests, ledger_blueprint())
        mutations, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, quest_name="账册疑云"
        )
        self.assertEqual(mutations, [])
        self.assertEqual([n["node_id"] for n in notices], ["heard"])

        upsert_fact(self.facts, FACT, "forged")
        mutations, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, fact_key=FACT
        )
        runtime = self.quests["runtimes"]["账册疑云"]
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

    def test_verified_conflict_allows_new_blueprint_without_exit(self):
        upsert_fact(self.facts, FACT, "forged")
        definition = normalize_quest_definition(ledger_blueprint(include_forged=False))
        self.assertTrue(validate_quest_definition(definition, self.facts, self.quests))

    def test_all_join_blueprint_is_not_rejected_by_fact_combinations(self):
        raw = {
            "名称": "不可能的汇合",
            "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None, "后继节点": ["authentic", "forged"]},
                {"节点ID": "authentic", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "authentic"},
                 "后继节点": ["finish"]},
                {"节点ID": "forged", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "forged"},
                 "后继节点": ["finish"]},
                {"节点ID": "finish", "关闭条件": None, "关闭描述": None, "前置节点": ["authentic", "forged"],
                 "汇合规则": "all", "终局": "关闭"},
            ],
        }
        definition = normalize_quest_definition(raw)
        self.assertTrue(validate_quest_definition(definition, self.facts, self.quests))

    def test_enum_coverage_does_not_check_cartesian_combinations(self):
        def outcome(node_id, authenticity, seal):
            return {
                "节点ID": node_id, "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                "完成条件": {"all": [
                    {"fact": FACT, "eq": authenticity},
                    {"fact": SEAL_FACT, "eq": seal},
                ]},
                "终局": "关闭",
            }

        raw = {
            "名称": "账册与封印",
            "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None, "后继节点": ["auth-intact", "auth-broken", "forged-intact"]},
                outcome("auth-intact", "authentic", "intact"),
                outcome("auth-broken", "authentic", "broken"),
                outcome("forged-intact", "forged", "intact"),
            ],
        }
        definition = normalize_quest_definition(raw)
        self.assertTrue(validate_quest_definition(definition, self.facts, self.quests))

    def test_close_condition_precedes_completion_and_blocks_successors(self):
        raw = {
            "名称": "断掉的证词", "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None,
                 "完成条件": {}, "后继节点": ["witness"]},
                {"节点ID": "witness", "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "forged"},
                 "完成摘要": "取得证词。",
                 "关闭条件": {"fact": FACT, "eq": "forged"},
                 "关闭描述": "证人已经离去，此路已断。",
                 "后继节点": ["finish"],
                 "奖励": {"奖励ID": "witness:reward", "描述": "不应发放",
                         "状态变更": [{"类型": "经验", "值": 100}] }},
                {"节点ID": "finish", "前置节点": ["witness"],
                 "关闭条件": None, "关闭描述": None,
                 "完成条件": {}, "终局": "解决"},
            ],
        }
        upsert_fact(self.facts, FACT, "forged")
        create_quest(self.facts, self.quests, raw)
        mutations, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, quest_name="断掉的证词"
        )
        runtime = self.quests["runtimes"]["断掉的证词"]
        self.assertEqual(mutations, [])
        self.assertEqual(runtime["completed_node_ids"], ["start"])
        self.assertEqual(runtime["closed_node_ids"], ["witness"])
        self.assertEqual(runtime["blocked_node_ids"], ["finish"])
        self.assertEqual(runtime["settled_node_ids"], ["start", "witness"])
        self.assertEqual(runtime["claimed_reward_ids"], [])
        self.assertEqual(runtime["lifecycle"], "closed")
        self.assertEqual(notices[-1]["summary"], "证人已经离去，此路已断。")
        self.assertEqual(
            [row["描述"] for row in project_clues(self.quests)[0]["进展节点"]],
            ["", "证人已经离去，此路已断。"],
        )
        upsert_fact(
            self.facts, FACT, "authentic", revision=True, reason="确认先前鉴定有误"
        )
        reduce_affected_quests(self.facts, self.quests, fact_key=FACT)
        self.assertEqual(runtime["closed_node_ids"], ["witness"])
        self.assertEqual(runtime["blocked_node_ids"], ["finish"])

    def test_all_join_blocks_but_any_join_keeps_other_path(self):
        def joined(name, join):
            return {
                "名称": name, "起始节点": ["start"],
                "节点": [
                    {"节点ID": "start", "关闭条件": None, "关闭描述": None,
                     "完成条件": {}, "后继节点": ["left", "right"]},
                    {"节点ID": "left", "前置节点": ["start"],
                     "关闭条件": {}, "关闭描述": "左路到此中断。",
                     "完成条件": {}, "后继节点": ["finish"]},
                    {"节点ID": "right", "前置节点": ["start"],
                     "关闭条件": None, "关闭描述": None,
                     "完成条件": {}, "后继节点": ["finish"]},
                    {"节点ID": "finish", "前置节点": ["left", "right"],
                     "汇合规则": join, "关闭条件": None, "关闭描述": None,
                     "完成条件": {}, "终局": "解决"},
                ],
            }

        create_quest(self.facts, self.quests, joined("必须双路", "all"))
        reduce_affected_quests(self.facts, self.quests, quest_name="必须双路")
        all_runtime = self.quests["runtimes"]["必须双路"]
        self.assertIn("finish", all_runtime["blocked_node_ids"])
        self.assertEqual(all_runtime["lifecycle"], "closed")

        create_quest(self.facts, self.quests, joined("任一路线", "any"))
        reduce_affected_quests(self.facts, self.quests, quest_name="任一路线")
        any_runtime = self.quests["runtimes"]["任一路线"]
        self.assertNotIn("finish", any_runtime["blocked_node_ids"])
        self.assertIn("finish", any_runtime["completed_node_ids"])
        self.assertEqual(any_runtime["lifecycle"], "resolved")

    def test_required_close_fields_and_nullable_pair(self):
        raw = ledger_blueprint()
        raw["节点"][0].pop("关闭条件")
        with self.assertRaisesRegex(ValueError, "须显式提供"):
            normalize_quest_definition(raw)

        raw = ledger_blueprint()
        raw["节点"][0]["关闭描述"] = "只传描述"
        with self.assertRaisesRegex(ValueError, "须同时为 null"):
            normalize_quest_definition(raw)

    def test_hidden_quest_waits_for_discovery_before_reduction(self):
        create_quest(self.facts, self.quests, ledger_blueprint(), hidden=True)
        _, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, quest_name="账册疑云"
        )
        self.assertEqual(notices, [])
        self.assertEqual(
            self.quests["runtimes"]["账册疑云"]["completed_node_ids"], []
        )
        discover_quest(self.quests, "账册疑云")
        _, _, notices, _ = reduce_affected_quests(
            self.facts, self.quests, quest_name="账册疑云"
        )
        self.assertEqual([item["node_id"] for item in notices], ["heard"])

    def test_pending_extension_gates_flag_reached_unactivated_points(self):
        raw = {
            "名称": "打回校验", "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None,
                 "完成条件": {}, "后继节点": ["gate", "settled"]},
                {"节点ID": "gate", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "authentic"},
                 "完成摘要": "到达扩展点。", "扩展点": True},
                {"节点ID": "settled", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "forged"},
                 "完成摘要": "线索就此了结。", "终局": "解决"},
            ],
        }
        create_quest(self.facts, self.quests, raw)
        reduce_affected_quests(self.facts, self.quests, quest_name="打回校验")
        # 前置已齐但条件未成立 → 不打回
        self.assertEqual(pending_extension_gates(self.facts, self.quests), [])
        # 条件成立 → 打回
        upsert_fact(self.facts, FACT, "authentic")
        self.assertEqual(
            pending_extension_gates(self.facts, self.quests), [("打回校验", "gate")]
        )
        # 已激活 → 不打回
        self.quests["runtimes"]["打回校验"]["activated_extension_ids"].append("gate")
        self.assertEqual(pending_extension_gates(self.facts, self.quests), [])

    def test_extension_must_activate_an_explicit_extension_point(self):
        raw = {
            "名称": "账册余波",
            "起始节点": ["heard"],
            "节点": [
                {"节点ID": "heard", "关闭条件": None, "关闭描述": None, "完成条件": {}, "完成摘要": "得知余波。",
                 "后继节点": ["authentic", "future"]},
                {"节点ID": "authentic", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
                 "完成条件": {"fact": FACT, "eq": "authentic"},
                 "完成摘要": "真账已有定论。", "终局": "解决"},
                {"节点ID": "future", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
                 "完成条件": {"fact": FACT, "eq": "forged"},
                 "完成摘要": "伪账牵出新的方向。", "扩展点": True},
            ],
        }
        create_quest(self.facts, self.quests, raw)
        with self.assertRaisesRegex(ValueError, "须指定 扩展点"):
            extend_quest(self.facts, self.quests, {
                "名称": "账册余波", "版本": 2,
                "起始节点": ["forged-end"],
                "节点": [{"节点ID": "forged-end", "关闭条件": None, "关闭描述": None, "终局": "关闭"}],
            })
        extended = extend_quest(self.facts, self.quests, {
            "名称": "账册余波", "扩展点": "future", "版本": 2,
            "起始节点": ["forged-end"],
            "节点": [{"节点ID": "forged-end", "关闭条件": None, "关闭描述": None, "前置节点": ["future"],
                       "完成摘要": "伪账后续已收束。", "终局": "关闭"}],
        })
        self.assertEqual(extended["nodes"]["future"]["next"], ["forged-end"])
        self.assertFalse(extended["nodes"]["future"]["extension"])

    def test_closed_extension_point_cannot_be_activated(self):
        raw = {
            "名称": "已断余波", "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None,
                 "完成条件": {}, "后继节点": ["done", "future"]},
                {"节点ID": "done", "前置节点": ["start"],
                 "关闭条件": None, "关闭描述": None,
                 "完成条件": {"fact": FACT, "eq": "authentic"}, "终局": "解决"},
                {"节点ID": "future", "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "authentic"},
                 "关闭条件": {"fact": FACT, "eq": "forged"},
                 "关闭描述": "后续已经断绝。", "扩展点": True},
            ],
        }
        create_quest(self.facts, self.quests, raw)
        upsert_fact(self.facts, FACT, "forged")
        reduce_affected_quests(self.facts, self.quests, fact_key=FACT)
        with self.assertRaisesRegex(ValueError, "扩展点.*已关闭"):
            extend_quest(self.facts, self.quests, {
                "名称": "已断余波", "扩展点": "future", "版本": 2,
                "起始节点": ["trace"],
                "节点": [{"节点ID": "trace", "前置节点": ["future"],
                         "关闭条件": None, "关闭描述": None, "终局": "关闭"}],
            })

    def test_extension_requires_description_only_for_new_fact_definitions(self):
        fact = "case:legacy.route@world"
        base = {
            "版本": 1, "名称": "旧档后续",
            "事实定义": [{"事实键": fact, "描述": "旧案后续走向",
                         "值类型": "enum", "可选值": ["done", "follow"]}],
            "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None, "后继节点": ["done", "future"]},
                {"节点ID": "done", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                 "完成条件": {"fact": fact, "eq": "done"}, "终局": "解决"},
                {"节点ID": "future", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                 "完成条件": {"fact": fact, "eq": "follow"}, "扩展点": True},
            ],
        }
        create_quest(self.facts, self.quests, base)
        self.facts["definitions"][fact].pop("description")
        self.quests["definitions"]["旧档后续"]["fact_definitions"][0].pop("描述")
        new_fact = "case:legacy.witness@world"
        with self.assertRaisesRegex(ValueError, "须提供非空 描述"):
            extend_quest(self.facts, self.quests, {
                "名称": "旧档后续", "扩展点": "future", "版本": 2,
                "事实定义": [{"事实键": new_fact, "值类型": "bool"}],
                "起始节点": ["trace-missing-description"],
                "节点": [{"节点ID": "trace-missing-description", "关闭条件": None, "关闭描述": None, "前置节点": ["future"],
                         "终局": "关闭"}],
            })

        full = {
            "版本": 2, "名称": "旧档后续",
            "事实定义": [{"事实键": fact, "值类型": "enum",
                         "可选值": ["done", "follow"]}],
            "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None, "后继节点": ["done", "future"]},
                {"节点ID": "done", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                 "完成条件": {"fact": fact, "eq": "done"}, "终局": "解决"},
                {"节点ID": "future", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
                 "完成条件": {"fact": fact, "eq": "follow"}, "后继节点": ["trace"]},
                {"节点ID": "trace", "关闭条件": None, "关闭描述": None, "前置节点": ["future"], "终局": "关闭"},
            ],
        }
        extended = extend_quest(self.facts, self.quests, {
            "任务": full, "扩展点": "future",
        })
        self.assertEqual(extended["version"], 2)

    def test_condition_dsl_rejects_unknown_and_mistyped_fields(self):
        with self.assertRaisesRegex(ValueError, "未知字段"):
            validate_condition({"fact": FACT, "eq": "forged", "阶段": "done"})
        with self.assertRaisesRegex(ValueError, "exists 须为 bool"):
            validate_condition({"fact": FACT, "exists": "yes"})
        with self.assertRaisesRegex(ValueError, "completed 须为 bool"):
            validate_condition({"node": "heard", "completed": 1})

    def test_projection_uses_completion_order_not_blueprint_order(self):
        definition = normalize_quest_definition(ledger_blueprint())
        self.quests["definitions"]["账册疑云"] = definition
        self.quests["runtimes"]["账册疑云"] = {
            "lifecycle": "active", "completed_node_ids": ["forged", "heard"]
        }
        projected = project_clues(self.quests)
        self.assertEqual(
            [item["描述"] for item in projected[0]["进展节点"]],
            ["查明账册系伪造。", "得知账册之谜。"],
        )

    def test_cross_quest_future_fact_effects_are_not_statically_rejected(self):
        def raw(name, value):
            return {
                "名称": name, "起始节点": ["end"],
                "节点": [{
                    "节点ID": "end", "关闭条件": None, "关闭描述": None,
                    "完成条件": {"fact": FACT, "eq": value}, "终局": "解决",
                    "效果": [{"类型": "事实", "事实": FACT, "值": value}],
                }],
            }
        create_quest(self.facts, self.quests, raw("真账结论", "authentic"))
        create_quest(self.facts, self.quests, raw("伪账结论", "forged"))
        self.assertEqual(set(self.quests["definitions"]), {"真账结论", "伪账结论"})

    def test_duplicate_clue_name_is_rejected(self):
        create_quest(self.facts, self.quests, ledger_blueprint())
        with self.assertRaisesRegex(ValueError, "已存在"):
            create_quest(self.facts, self.quests, ledger_blueprint())

    def test_new_blueprint_rejects_legacy_task_id(self):
        raw = ledger_blueprint()
        raw["任务ID"] = "legacy-id"
        with self.assertRaisesRegex(ValueError, "不再接受 任务ID"):
            create_quest(self.facts, self.quests, raw)

    def test_old_id_keyed_state_migrates_to_clue_name(self):
        migrated = normalize_quest_state({
            "version": 1,
            "definitions": {
                "legacy-id": {"quest_id": "legacy-id", "name": "旧案"},
            },
            "runtimes": {
                "legacy-id": {"quest_id": "legacy-id", "lifecycle": "active"},
            },
            "legacy_imported": True,
        })
        self.assertEqual(migrated["version"], 3)
        self.assertEqual(set(migrated["definitions"]), {"旧案"})
        self.assertEqual(set(migrated["runtimes"]), {"旧案"})
        self.assertNotIn("quest_id", migrated["definitions"]["旧案"])
        self.assertNotIn("quest_id", migrated["runtimes"]["旧案"])
        self.assertEqual(migrated["runtimes"]["旧案"]["closed_node_ids"], [])
        self.assertEqual(migrated["runtimes"]["旧案"]["blocked_node_ids"], [])
        self.assertEqual(migrated["runtimes"]["旧案"]["settled_node_ids"], [])

    def test_v2_state_adds_close_fields_and_runtime_history(self):
        migrated = normalize_quest_state({
            "version": 2,
            "definitions": {"旧线索": {
                "name": "旧线索", "nodes": {"start": {
                    "node_id": "start", "condition": {}, "summary": "旧进展",
                    "next": [], "outcome": "closed", "visible": True,
                    "extension": False, "reward": None, "effects": [],
                }},
            }},
            "runtimes": {"旧线索": {
                "lifecycle": "closed", "completed_node_ids": ["start"],
            }},
        })
        node = migrated["definitions"]["旧线索"]["nodes"]["start"]
        runtime = migrated["runtimes"]["旧线索"]
        self.assertIsNone(node["close_condition"])
        self.assertIsNone(node["close_summary"])
        self.assertEqual(runtime["settled_node_ids"], ["start"])
        self.assertEqual(runtime["closed_node_ids"], [])
        self.assertEqual(runtime["blocked_node_ids"], [])

    def test_old_id_keyed_state_rejects_duplicate_clue_names(self):
        with self.assertRaisesRegex(ValueError, "old-a.*old-b.*同名旧案"):
            normalize_quest_state({
                "version": 1,
                "definitions": {
                    "old-a": {"quest_id": "old-a", "name": "同名旧案"},
                    "old-b": {"quest_id": "old-b", "name": "同名旧案"},
                },
                "runtimes": {},
            })

    def test_potential_hints_group_same_fact_by_task_and_node(self):
        create_quest(self.facts, self.quests, ledger_blueprint())
        reduce_affected_quests(self.facts, self.quests, quest_name="账册疑云")
        second = ledger_blueprint()
        second["名称"] = "账册余案"
        create_quest(self.facts, self.quests, second)
        reduce_affected_quests(self.facts, self.quests, quest_name="账册余案")

        self.assertEqual(potential_progress_hints(self.facts, self.quests), [{
            "类型": "潜在线索变化",
            "候选事实": FACT,
            "事实描述": "账册的真实真伪",
            "影响线索": [
                {"名称": "账册余案", "节点ID列表": ["authentic", "forged"]},
                {"名称": "账册疑云", "节点ID列表": ["authentic", "forged"]},
            ],
            "提示": "若剧情已确认该语义事实，请在 judge 中提交事实变更；当前尚未推进相关节点",
        }])

    def test_potential_hints_include_close_condition_facts(self):
        raw = {
            "名称": "会中断的追查", "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None,
                 "完成条件": {}, "后继节点": ["finish"]},
                {"节点ID": "finish", "前置节点": ["start"],
                 "完成条件": {"fact": FACT, "eq": "authentic"},
                 "关闭条件": {"fact": SEAL_FACT, "eq": "broken"},
                 "关闭描述": "封印已毁，追查中断。", "终局": "解决"},
            ],
        }
        create_quest(self.facts, self.quests, raw)
        reduce_affected_quests(self.facts, self.quests, quest_name="会中断的追查")
        hints = potential_progress_hints(self.facts, self.quests)
        self.assertEqual(
            {hint["候选事实"] for hint in hints if hint["类型"] == "潜在线索变化"},
            {FACT, SEAL_FACT},
        )

    def test_potential_hints_skip_impossible_node(self):
        definition = normalize_quest_definition({
            "名称": "受阻分支", "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None, "后继节点": ["finish"]},
                {"节点ID": "finish", "关闭条件": None, "关闭描述": None, "前置节点": ["start"], "完成条件": {"all": [
                    {"fact": FACT, "eq": "authentic"},
                    {"fact": SEAL_FACT, "eq": "intact"},
                ]}, "终局": "关闭"},
            ],
        })
        self.quests["definitions"]["受阻分支"] = definition
        self.quests["runtimes"]["受阻分支"] = {
            "lifecycle": "active", "completed_node_ids": ["start"]
        }
        upsert_fact(self.facts, FACT, "forged")
        self.assertEqual(potential_progress_hints(self.facts, self.quests), [])

    def test_potential_hints_keep_possible_unknown_and_default_legacy_description(self):
        definition = normalize_quest_definition({
            "名称": "可行分支", "起始节点": ["start"],
            "节点": [
                {"节点ID": "start", "关闭条件": None, "关闭描述": None, "后继节点": ["finish"]},
                {"节点ID": "finish", "关闭条件": None, "关闭描述": None, "前置节点": ["start"], "完成条件": {"all": [
                    {"fact": FACT, "eq": "authentic"},
                    {"fact": SEAL_FACT, "eq": "intact"},
                ]}, "终局": "关闭"},
            ],
        })
        self.quests["definitions"]["可行分支"] = definition
        self.quests["runtimes"]["可行分支"] = {
            "lifecycle": "active", "completed_node_ids": ["start"]
        }
        upsert_fact(self.facts, FACT, "authentic")
        self.facts["definitions"][SEAL_FACT].pop("description")
        hints = potential_progress_hints(self.facts, self.quests)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["候选事实"], SEAL_FACT)
        self.assertEqual(hints[0]["事实描述"], "")

    def test_new_quest_fact_definition_requires_description(self):
        raw = ledger_blueprint()
        raw["名称"] = "缺描述事实"
        raw["事实定义"] = [{
            "事实键": "case:missing.description@world", "值类型": "bool",
        }]
        with self.assertRaisesRegex(ValueError, "须提供非空 描述"):
            create_quest(self.facts, self.quests, raw)


def hidden_entry_blueprint():
    """双分支入口蓝图：枚举两值各有入口与出口，满足校验器覆盖要求。"""
    return {
        "名称": "暗账", "引子": "一册来历不明的旧账浮出水面。",
        "隐藏目标": "查清旧账真伪及其背后牵连。",
        "起始节点": ["entry-forged", "entry-authentic"],
        "节点": [
            {"节点ID": "entry-forged", "关闭条件": None, "关闭描述": None, "完成条件": {"fact": FACT, "eq": "forged"},
             "完成摘要": "伪账浮出。", "后继节点": ["close-forged"]},
            {"节点ID": "close-forged", "关闭条件": None, "关闭描述": None, "前置节点": ["entry-forged"], "完成条件": {},
             "完成摘要": "伪账收束。", "终局": "关闭"},
            {"节点ID": "entry-authentic", "关闭条件": None, "关闭描述": None, "完成条件": {"fact": FACT, "eq": "authentic"},
             "完成摘要": "真账浮出。", "后继节点": ["resolve-authentic"]},
            {"节点ID": "resolve-authentic", "关闭条件": None, "关闭描述": None, "前置节点": ["entry-authentic"], "完成条件": {},
             "完成摘要": "真账收束。", "终局": "解决"},
        ],
    }


class HiddenEntryHintTest(unittest.TestCase):
    def setUp(self):
        self.facts = empty_world_facts()
        register_definition(self.facts, {
            "事实键": FACT, "描述": "账册的真实真伪",
            "值类型": "enum", "可选值": ["authentic", "forged"],
        })
        self.quests = empty_quest_state()

    def test_hidden_entry_hint_fires_when_condition_satisfied(self):
        upsert_fact(self.facts, FACT, "forged")
        create_quest(self.facts, self.quests, hidden_entry_blueprint(), hidden=True)
        hints = potential_progress_hints(self.facts, self.quests)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["类型"], "隐藏线索")
        self.assertEqual(hints[0]["线索"], "暗账")
        self.assertEqual(hints[0]["入口节点"], "entry-forged")
        self.assertEqual(hints[0]["引子"], "一册来历不明的旧账浮出水面。")
        self.assertEqual(hints[0]["隐藏目标"], "查清旧账真伪及其背后牵连。")
        self.assertEqual(hints[0]["入口摘要"], "伪账浮出。")

    def test_discovery_reduces_the_satisfied_entry_node(self):
        upsert_fact(self.facts, FACT, "forged")
        create_quest(self.facts, self.quests, hidden_entry_blueprint(), hidden=True)
        discover_quest(self.quests, "暗账")
        _mutations, _events, notices, _hints = reduce_affected_quests(
            self.facts, self.quests, quest_name="暗账"
        )
        runtime = self.quests["runtimes"]["暗账"]
        self.assertEqual(runtime["completed_node_ids"], ["entry-forged", "close-forged"])
        self.assertEqual(runtime["lifecycle"], "closed")
        self.assertEqual(
            [notice["node_id"] for notice in notices],
            ["entry-forged", "close-forged"],
        )

    def test_hidden_entry_hint_silent_when_condition_unsatisfied(self):
        create_quest(self.facts, self.quests, hidden_entry_blueprint(), hidden=True)
        self.assertEqual(potential_progress_hints(self.facts, self.quests), [])

    def test_hidden_entry_hint_silent_for_unconditional_entry(self):
        create_quest(self.facts, self.quests, ledger_blueprint(), hidden=True)
        self.assertEqual(potential_progress_hints(self.facts, self.quests), [])

    def test_hidden_entry_hint_stops_after_discovery(self):
        upsert_fact(self.facts, FACT, "forged")
        create_quest(self.facts, self.quests, hidden_entry_blueprint(), hidden=True)
        discover_quest(self.quests, "暗账")
        self.assertEqual(
            [h["类型"] for h in potential_progress_hints(self.facts, self.quests)],
            [],
        )


class MechanicalLocationFactTest(unittest.TestCase):
    def test_player_location_change_writes_full_location_and_region(self):
        event = EventFactory(1, "test").create(
            LOCATION_CHANGED, {"after": "苏州城·阊门驿"}
        )
        mutations = _mechanical_fact_mutations(event)
        self.assertEqual(
            [(item["事实"], item["值"]) for item in mutations],
            [
                ("player.location@world", "苏州城·阊门驿"),
                ("player.region@world", "苏州城"),
            ],
        )
        self.assertTrue(all(
            item["_定义"]["修订策略"] == "free" for item in mutations
        ))

    def test_npc_location_change_does_not_rewrite_player_region(self):
        event = EventFactory(1, "test").create(
            LOCATION_CHANGED,
            {"character": "路人甲", "after": "杭州城·武林门驿"},
        )
        mutations = _mechanical_fact_mutations(event)
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0]["事实"], "character:路人甲.location@world")


if __name__ == "__main__":
    unittest.main()
