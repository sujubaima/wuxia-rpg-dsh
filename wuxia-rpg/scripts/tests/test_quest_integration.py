#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务状态机与 SettlementSession、奖励、回滚和 legacy 投影集成。"""
import copy
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from common.json_io import JsonSchemaError
from engine import _attach_quest_hints, _public_results
from settle.engine_actions import build_mutation_executor
from settle.quest_triggers import build_quest_trigger_registry
from settle.settlement import SettlementSession
from settle.quest_engine import create_quest, extend_quest
from settle.quest_models import empty_quest_state
from settle.world_facts import empty_world_facts
from store import quest_drafts


FACT = "scene:study.secret_found@world"
EXTENSION_FACT = "scene:study.follow_up_route@world"


def blueprint(task_id="study-secret", fact=FACT, name="书房暗痕"):
    return {
        "任务ID": task_id, "名称": name, "引子": "书房中似有异样。",
        "隐藏目标": "确认暗格是否存在",
        "事实定义": [{"事实键": fact, "值类型": "enum", "可选值": ["found", "absent"]}],
        "起始节点": ["investigate"],
        "节点": [
            {"节点ID": "investigate", "完成条件": {}, "完成摘要": "开始调查书房。",
             "后继节点": ["found", "absent"]},
            {"节点ID": "found", "前置节点": ["investigate"],
             "完成条件": {"fact": fact, "eq": "found"}, "完成摘要": "发现墙后的暗格。",
             "终局": "解决", "奖励": {"奖励ID": f"{task_id}:found:reward", "描述": "体力+10",
                                      "状态变更": [{"类型": "体力", "操作": "加", "值": 10}] }},
            {"节点ID": "absent", "前置节点": ["investigate"],
             "完成条件": {"fact": fact, "eq": "absent"}, "完成摘要": "确认书房没有暗格。",
             "终局": "关闭"},
        ],
    }


def draft_record(hidden=False, task_id="study-secret", fact=FACT, name="书房暗痕"):
    facts = empty_world_facts()
    quests = empty_quest_state()
    raw = blueprint(task_id, fact, name)
    definition = create_quest(facts, quests, raw, hidden=hidden)
    digest = quest_drafts.definition_hash("create", definition, hidden)
    return {
        "kind": "create",
        "payload": raw,
        "hidden": hidden,
        "content_hash": digest,
        "quest_id": definition["quest_id"],
        "definition_version": definition["version"],
        "summary": {"名称": definition["name"]},
    }


def draft_batch(*records, round_number=0):
    return {"slot": 1, "round": round_number, "records": list(records)}


def extension_blueprints():
    base = {
        "任务ID": "study-follow-up", "版本": 1, "名称": "书房余波",
        "引子": "暗格之后另有隐情。", "隐藏目标": "追查余波",
        "事实定义": [
            {"事实键": EXTENSION_FACT, "值类型": "enum", "可选值": ["done", "follow"]},
        ],
        "起始节点": ["start"],
        "节点": [
            {"节点ID": "start", "完成条件": {}, "完成摘要": "开始核对余波。",
             "后继节点": ["done", "follow-up"]},
            {"节点ID": "done", "前置节点": ["start"],
             "完成条件": {"fact": EXTENSION_FACT, "eq": "done"},
             "完成摘要": "余波自行平息。", "终局": "关闭"},
            {"节点ID": "follow-up", "前置节点": ["start"],
             "完成条件": {"fact": EXTENSION_FACT, "eq": "follow"},
             "完成摘要": "仍有后续。", "扩展点": True},
        ],
    }
    extension = {
        "任务ID": "study-follow-up", "扩展点": "follow-up", "版本": 2,
        "起始节点": ["trace"],
        "节点": [
            {"节点ID": "trace", "前置节点": ["follow-up"], "完成条件": {},
             "完成摘要": "余波已查清。", "终局": "关闭"},
        ],
    }
    return base, extension


def extension_draft_record(facts, quests):
    _base, extension = extension_blueprints()
    candidate_facts = copy.deepcopy(facts)
    candidate_quests = copy.deepcopy(quests)
    definition = extend_quest(candidate_facts, candidate_quests, extension)
    digest = quest_drafts.definition_hash("extend", definition)
    return {
        "kind": "extend",
        "payload": extension,
        "hidden": False,
        "content_hash": digest,
        "quest_id": definition["quest_id"],
        "definition_version": definition["version"],
        "summary": {"名称": definition["name"]},
    }


class QuestSettlementIntegrationTest(unittest.TestCase):
    def _patch_storage(self, facts=None, quests=None):
        return patch.multiple(
            "settle.settlement.sm",
            read_world_facts=lambda slot: facts or {},
            read_quest_state=lambda slot: quests or {},
            write_world_facts=unittest.mock.DEFAULT,
            write_quest_state=unittest.mock.DEFAULT,
            write_merchant_cache=unittest.mock.DEFAULT,
        )

    def test_blueprint_fact_reward_projection_and_notice_commit_together(self):
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage() as mocked, \
             patch("settle.settlement.sc.commit_staged"), \
             patch("settle.settlement.dq.write_character"), \
             patch("settle.settlement.dq.update_char"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-创建", "任务": blueprint()},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                ])
                self.assertTrue(all(row["ok"] for row in results))
                self.assertEqual(explore["体力"], 60)
                self.assertEqual(session.public_notice_results(), [])
                session.commit()
                notices = session.public_notice_results()
                self.assertEqual(notices, [{
                    "ok": True,
                    "msg": "线索【书房暗痕】已发现",
                    "变更": "线索【书房暗痕】已发现",
                }])
                public = _public_results(results) + notices
                self.assertFalse(any(
                    str(row.get("变更") or "").startswith("事实【")
                    for row in public
                ))
                clue_changes = [
                    row.get("变更") for row in public
                    if str(row.get("变更") or "").startswith("线索【")
                ]
                self.assertEqual(clue_changes, ["线索【书房暗痕】已发现"])
            mocked["write_world_facts"].assert_called_once()
            mocked["write_quest_state"].assert_called_once()
        self.assertEqual(explore["任务摘要及进度"][0]["名称"], "书房暗痕")
        self.assertTrue(explore["任务摘要及进度"][0]["关闭"])
        self.assertEqual(len(explore["任务摘要及进度"][0]["进展节点"]), 2)

    def test_prepared_blueprint_adopts_with_fact_reward_and_notice(self):
        record = draft_record()
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage() as mocked, \
             patch("settle.engine_actions.qd.select_drafts", return_value=draft_batch(record)), \
             patch("settle.engine_actions.sm.read_round", return_value=0), \
             patch("settle.settlement.sc.commit_staged"), \
             patch("settle.settlement.dq.write_character"), \
             patch("settle.settlement.dq.update_char"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-采用草稿", "任务ID列表": [record["quest_id"]]},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                self.assertEqual(explore["体力"], 60)
                session.commit()
                self.assertEqual(session.public_notice_results(), [{
                    "ok": True,
                    "msg": "线索【书房暗痕】已发现",
                    "变更": "线索【书房暗痕】已发现",
                }])
            mocked["write_world_facts"].assert_called_once()
            mocked["write_quest_state"].assert_called_once()
        self.assertTrue(explore["任务摘要及进度"][0]["关闭"])

    def test_existing_clue_progress_emits_one_generic_update(self):
        facts = empty_world_facts()
        quests = empty_quest_state()
        create_quest(facts, quests, blueprint())
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage(facts, quests), \
             patch("settle.settlement.sc.commit_staged"), \
             patch("settle.settlement.dq.write_character"), \
             patch("settle.settlement.dq.update_char"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "事实", "事实": FACT, "值": "found"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                self.assertEqual(session.public_notice_results(), [])
                session.commit()
                self.assertEqual(session.public_notice_results(), [{
                    "ok": True,
                    "msg": "线索【书房暗痕】已更新",
                    "变更": "线索【书房暗痕】已更新",
                }])
        self.assertEqual(explore["体力"], 60)
        self.assertEqual(
            [node["描述"] for node in explore["任务摘要及进度"][0]["进展节点"]],
            ["开始调查书房。", "发现墙后的暗格。"],
        )

    def test_discovery_precedes_same_settlement_progress_notice(self):
        facts = empty_world_facts()
        quests = empty_quest_state()
        create_quest(facts, quests, blueprint(), hidden=True)
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage(facts, quests), \
             patch("settle.settlement.sc.commit_staged"), \
             patch("settle.settlement.dq.write_character"), \
             patch("settle.settlement.dq.update_char"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-发现", "任务ID": "study-secret"},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                self.assertTrue(results[0]["_静默"])
                session.commit()
                self.assertEqual(session.public_notice_results(), [{
                    "ok": True,
                    "msg": "线索【书房暗痕】已发现",
                    "变更": "线索【书房暗痕】已发现",
                }])
        self.assertTrue(explore["任务摘要及进度"][0]["关闭"])

    def test_repeated_discovery_is_silent(self):
        facts = empty_world_facts()
        quests = empty_quest_state()
        create_quest(facts, quests, blueprint())
        explore = {"任务摘要及进度": []}
        with self._patch_storage(facts, quests), \
             patch("settle.settlement.sc.commit_staged"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-发现", "任务ID": "study-secret"},
                ])
                self.assertTrue(results[0]["ok"])
                self.assertTrue(results[0]["_静默"])
                session.commit()
                self.assertEqual(session.public_notice_results(), [])

    def test_multiple_prepared_blueprints_adopt_together(self):
        second_fact = "scene:garden.secret_found@world"
        first = draft_record()
        second = draft_record(
            task_id="garden-secret", fact=second_fact, name="园中暗痕"
        )
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage(), \
             patch("settle.engine_actions.qd.select_drafts",
                   return_value=draft_batch(first, second)), \
             patch("settle.engine_actions.sm.read_round", return_value=0):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-采用草稿",
                     "任务ID列表": ["garden-secret", "study-secret"]},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                    {"类型": "事实", "事实": second_fact, "值": "found"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                self.assertEqual(
                    [row.get("_quest_id") for row in results[:2]],
                    ["study-secret", "garden-secret"],
                )
                self.assertEqual(set(session.quest_state["definitions"]),
                                 {"study-secret", "garden-secret"})
                self.assertEqual(explore["体力"], 70)

    def test_prepared_extension_adopts_and_reduces(self):
        facts = empty_world_facts()
        quests = empty_quest_state()
        base, _extension = extension_blueprints()
        create_quest(facts, quests, base)
        record = extension_draft_record(facts, quests)
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage(facts, quests), \
             patch("settle.engine_actions.qd.select_drafts", return_value=draft_batch(record)), \
             patch("settle.engine_actions.sm.read_round", return_value=0), \
             patch("settle.settlement.sc.commit_staged"), \
             patch("settle.settlement.dq.write_character"), \
             patch("settle.settlement.dq.update_char"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-采用草稿", "任务ID列表": [record["quest_id"]]},
                    {"类型": "事实", "事实": EXTENSION_FACT, "值": "follow"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                definition = session.quest_state["definitions"]["study-follow-up"]
                runtime = session.quest_state["runtimes"]["study-follow-up"]
                self.assertEqual(definition["version"], 2)
                self.assertIn("follow-up", runtime["activated_extension_ids"])
                self.assertEqual(runtime["lifecycle"], "closed")
                session.commit()
                self.assertEqual(session.public_notice_results(), [{
                    "ok": True,
                    "msg": "线索【书房余波】已更新",
                    "变更": "线索【书房余波】已更新",
                }])

    def test_prepared_hidden_blueprint_stays_hidden(self):
        record = draft_record(hidden=True)
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage(), \
             patch("settle.engine_actions.qd.select_drafts", return_value=draft_batch(record)), \
             patch("settle.engine_actions.sm.read_round", return_value=0):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-采用草稿", "任务ID列表": [record["quest_id"]]},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                ])
                runtime = session.quest_state["runtimes"]["study-secret"]
                self.assertTrue(all(row["ok"] for row in results), results)
                self.assertTrue(results[0]["_静默"])
                self.assertEqual(runtime["lifecycle"], "hidden")
                self.assertEqual(runtime["completed_node_ids"], [])
                self.assertEqual(explore["任务摘要及进度"], [])
                self.assertEqual(session.public_notice_results(), [])

    def test_prepared_blueprint_rejects_stale_round(self):
        record = draft_record()
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage() as mocked, \
             patch("settle.engine_actions.qd.select_drafts",
                   return_value=draft_batch(record, round_number=2)), \
             patch("settle.engine_actions.sm.read_round", return_value=3):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-采用草稿", "任务ID列表": [record["quest_id"]]},
                ])
                self.assertFalse(results[0]["ok"])
                self.assertIn("须重新 prepare", results[0]["msg"])
            mocked["write_world_facts"].assert_not_called()
            mocked["write_quest_state"].assert_not_called()

    def test_prepared_blueprint_rejects_tampered_payload(self):
        record = draft_record()
        record["payload"] = copy.deepcopy(record["payload"])
        record["payload"]["名称"] = "被篡改的书房暗痕"
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage() as mocked, \
             patch("settle.engine_actions.qd.select_drafts", return_value=draft_batch(record)), \
             patch("settle.engine_actions.sm.read_round", return_value=0):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-采用草稿", "任务ID列表": [record["quest_id"]]},
                ])
                self.assertFalse(results[0]["ok"])
                self.assertIn("已过期", results[0]["msg"])
            mocked["write_world_facts"].assert_not_called()
            mocked["write_quest_state"].assert_not_called()

    def test_prepared_blueprint_revalidates_authoritative_state(self):
        record = draft_record()
        facts = empty_world_facts()
        quests = empty_quest_state()
        create_quest(facts, quests, blueprint())
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage(facts, quests) as mocked, \
             patch("settle.engine_actions.qd.select_drafts", return_value=draft_batch(record)), \
             patch("settle.engine_actions.sm.read_round", return_value=0):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-采用草稿", "任务ID列表": [record["quest_id"]]},
                ])
                self.assertFalse(results[0]["ok"])
                self.assertIn("须重新 prepare", results[0]["msg"])
            mocked["write_world_facts"].assert_not_called()
            mocked["write_quest_state"].assert_not_called()

    def test_corrupt_draft_is_reported_as_mutation_failure(self):
        explore = {"体力": 50, "任务摘要及进度": []}
        error = JsonSchemaError("/tmp/quest_drafts.json", "草稿结构损坏")
        with self._patch_storage() as mocked, \
             patch("settle.engine_actions.qd.select_drafts", side_effect=error):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-采用草稿", "任务ID列表": ["study-secret"]},
                ])
                self.assertFalse(results[0]["ok"])
                self.assertIn("读取失败", results[0]["msg"])
                self.assertIn("须重新 prepare", results[0]["msg"])
            mocked["write_world_facts"].assert_not_called()
            mocked["write_quest_state"].assert_not_called()

    def test_hidden_blueprint_does_not_progress_or_leak_before_discovery(self):
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage():
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-创建", "任务": blueprint(), "隐藏": True},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                ])
                runtime = session.quest_state["runtimes"]["study-secret"]
                self.assertTrue(results[0]["_静默"])
                self.assertEqual(runtime["lifecycle"], "hidden")
                self.assertEqual(runtime["completed_node_ids"], [])
                self.assertEqual(explore["任务摘要及进度"], [])
                self.assertEqual(session.public_notice_results(), [])
                public = _public_results(results)
                self.assertFalse(any("书房暗痕" in str(item) for item in public))

    def test_engine_output_keeps_quest_hints_gm_only(self):
        response = {"结算": [{"ok": True, "变更": "体力-1"}]}
        hints = [{"类型": "潜在线索变化", "任务ID": "study-secret"}]
        result = _attach_quest_hints(response, hints)
        self.assertEqual(result["结算"], [{"ok": True, "变更": "体力-1"}])
        self.assertEqual(result["GM线索提示"], hints)

    def test_legacy_direct_clue_mutation_is_rejected(self):
        explore = {"任务摘要及进度": []}
        with self._patch_storage():
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索", "名称": "旧写法", "进展节点": []}
                ])
                self.assertFalse(results[0]["ok"])
                self.assertIn("未知状态变更类型", results[0]["msg"])

    def test_failed_reward_discards_fact_and_quest_files(self):
        bad = blueprint()
        bad["节点"][1]["奖励"]["状态变更"] = [
            {"类型": "并不存在", "值": 1}
        ]
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage() as mocked:
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-创建", "任务": bad},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                ])
                self.assertTrue(any(not row["ok"] for row in results))
            mocked["write_world_facts"].assert_not_called()
            mocked["write_quest_state"].assert_not_called()

    def test_legacy_clue_is_imported_without_reward_reissue(self):
        explore = {"任务摘要及进度": [{
            "名称": "旧线索", "进展节点": [{"描述": "旧进展", "奖励": "经验500"}],
            "关闭": True,
        }]}
        with self._patch_storage() as mocked:
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                runtime = next(iter(session.quest_state["runtimes"].values()))
                self.assertEqual(len(runtime["claimed_reward_ids"]), 1)
                self.assertEqual(explore["任务摘要及进度"][0]["进展节点"][0]["奖励"], "经验500")
                session.commit()
            mocked["write_quest_state"].assert_called_once()

    def test_open_legacy_clue_keeps_an_extension_point(self):
        explore = {"任务摘要及进度": [{
            "名称": "未完旧线索", "进展节点": [{"描述": "追查至旧宅"}],
            "关闭": False,
        }]}
        with self._patch_storage():
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                definition = next(iter(session.quest_state["definitions"].values()))
                last_node = definition["nodes"]["legacy-node-1"]
                self.assertTrue(last_node["extension"])
                self.assertEqual(last_node["next"], [])


if __name__ == "__main__":
    unittest.main()
