#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务状态机与 SettlementSession、奖励、回滚和 legacy 投影集成。"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from common.json_io import JsonSchemaError
from engine import _attach_quest_hints, _public_results
from settle.engine_actions import _act_create_slot, build_mutation_executor
from quest.triggers import build_quest_trigger_registry
from settle import engine_state as est
from settle.settlement import SettlementSession
from quest.engine import create_quest, extend_quest
from quest.models import empty_quest_state
from quest.presets import build_initial_preset_state
from quest.world_facts import empty_world_facts
from store import quest_drafts


FACT = "scene:study.secret_found@world"
EXTENSION_FACT = "scene:study.follow_up_route@world"


def blueprint(reward_prefix="study-secret", fact=FACT, name="书房暗痕"):
    return {
        "名称": name, "引子": "书房中似有异样。",
        "隐藏目标": "确认暗格是否存在",
        "事实定义": [{"事实键": fact, "描述": "书房暗格是否存在", "值类型": "enum", "可选值": ["found", "absent"]}],
        "起始节点": ["investigate"],
        "节点": [
            {"节点ID": "investigate", "关闭条件": None, "关闭描述": None, "完成条件": {}, "完成摘要": "开始调查书房。",
             "后继节点": ["found", "absent"]},
            {"节点ID": "found", "关闭条件": None, "关闭描述": None, "前置节点": ["investigate"],
             "完成条件": {"fact": fact, "eq": "found"}, "完成摘要": "发现墙后的暗格。",
             "终局": "解决", "奖励": {"奖励ID": f"{reward_prefix}:found:reward", "描述": "体力+10",
                                      "状态变更": [{"类型": "体力", "操作": "加", "值": 10}] }},
            {"节点ID": "absent", "关闭条件": None, "关闭描述": None, "前置节点": ["investigate"],
             "完成条件": {"fact": fact, "eq": "absent"}, "完成摘要": "确认书房没有暗格。",
             "终局": "关闭"},
        ],
    }


def draft_record(hidden=False, reward_prefix="study-secret", fact=FACT, name="书房暗痕"):
    facts = empty_world_facts()
    quests = empty_quest_state()
    raw = blueprint(reward_prefix, fact, name)
    definition = create_quest(facts, quests, raw, hidden=hidden)
    digest = quest_drafts.definition_hash("create", definition, hidden)
    return {
        "kind": "create",
        "payload": raw,
        "hidden": hidden,
        "content_hash": digest,
        "quest_name": definition["name"],
        "definition_version": definition["version"],
        "summary": {"名称": definition["name"]},
    }


def draft_batch(*records, round_number=0):
    return {"slot": 1, "round": round_number, "records": list(records)}


def extension_blueprints():
    base = {
        "版本": 1, "名称": "书房余波",
        "引子": "暗格之后另有隐情。", "隐藏目标": "追查余波",
        "事实定义": [
            {"事实键": EXTENSION_FACT, "描述": "书房余波是否仍需追查", "值类型": "enum", "可选值": ["done", "follow"]},
        ],
        "起始节点": ["start"],
        "节点": [
            {"节点ID": "start", "关闭条件": None, "关闭描述": None, "完成条件": {}, "完成摘要": "开始核对余波。",
             "后继节点": ["done", "follow-up"]},
            {"节点ID": "done", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
             "完成条件": {"fact": EXTENSION_FACT, "eq": "done"},
             "完成摘要": "余波自行平息。", "终局": "关闭"},
            {"节点ID": "follow-up", "关闭条件": None, "关闭描述": None, "前置节点": ["start"],
             "完成条件": {"fact": EXTENSION_FACT, "eq": "follow"},
             "完成摘要": "仍有后续。", "扩展点": True},
        ],
    }
    extension = {
        "名称": "书房余波", "扩展点": "follow-up", "版本": 2,
        "起始节点": ["trace"],
        "节点": [
            {"节点ID": "trace", "关闭条件": None, "关闭描述": None, "前置节点": ["follow-up"], "完成条件": {},
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
        "quest_name": definition["name"],
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
                    {"类型": "线索-采用草稿", "名称列表": [record["quest_name"]]},
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

    def test_close_condition_projects_description_without_normal_reward(self):
        raw = blueprint()
        raw["名称"] = "暗格线索中断"
        raw["节点"] = [
            {"节点ID": "investigate", "关闭条件": None, "关闭描述": None,
             "完成条件": {}, "完成摘要": "开始调查书房。",
             "后继节点": ["found"]},
            {"节点ID": "found", "前置节点": ["investigate"],
             "完成条件": {"fact": FACT, "eq": "found"},
             "完成摘要": "发现墙后的暗格。",
             "关闭条件": {"fact": FACT, "eq": "absent"},
             "关闭描述": "确认书房并无暗格，此路已断。",
             "后继节点": ["finish"],
             "奖励": {"奖励ID": "closed-path:reward", "描述": "体力+10",
                     "状态变更": [{"类型": "体力", "操作": "加", "值": 10}]}},
            {"节点ID": "finish", "前置节点": ["found"],
             "关闭条件": None, "关闭描述": None,
             "完成条件": {}, "终局": "解决"},
        ]
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage(), \
             patch("settle.settlement.sc.commit_staged"), \
             patch("settle.settlement.dq.write_character"), \
             patch("settle.settlement.dq.update_char"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "线索-创建", "任务": raw},
                    {"类型": "事实", "事实": FACT, "值": "absent"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                runtime = session.quest_state["runtimes"]["暗格线索中断"]
                self.assertEqual(runtime["lifecycle"], "closed")
                self.assertEqual(runtime["closed_node_ids"], ["found"])
                self.assertEqual(runtime["blocked_node_ids"], ["finish"])
                self.assertEqual(runtime["claimed_reward_ids"], [])
                session.commit()
        self.assertEqual(explore["体力"], 50)
        self.assertEqual(
            [row["描述"] for row in explore["任务摘要及进度"][0]["进展节点"]],
            ["开始调查书房。", "确认书房并无暗格，此路已断。"],
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
                    {"类型": "线索-发现", "名称": "书房暗痕"},
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

    def test_contact_mutation_writes_contact_fact(self):
        facts = empty_world_facts()
        quests = empty_quest_state()
        explore = {"体力": 50, "任务摘要及进度": []}
        with self._patch_storage(facts, quests), \
             patch("settle.settlement.sc.commit_staged"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "go", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "接触记录", "角色": "石敬岩"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                record = session.world_facts["records"].get(
                    "character:石敬岩.contact@player")
        self.assertIsNotNone(record)
        self.assertTrue(record["value"])
        self.assertEqual(record["status"], "verified")

    def test_opening_judge_discovers_and_reduces_real_preset(self):
        data_dir = os.path.join(os.path.dirname(SCRIPTS), "assets", "data")
        preset = build_initial_preset_state(
            data_dir,
            {"名称": "试剑人"},
            {"当前位置": "苏州城", "当前时间": 0, "体力": 100},
        )
        explore = {"任务摘要及进度": []}
        with self._patch_storage(preset["world_facts"], preset["quest_state"]), \
             patch("settle.settlement.sc.commit_staged"):
            with SettlementSession(
                1, explore, build_mutation_executor(), "judge", build_quest_trigger_registry()
            ) as session:
                results = session.apply_mutations([
                    {"类型": "事实-写入", "事实": "quest:v3:taihu.hook@world",
                     "值": True, "状态": "verified"},
                    {"类型": "线索-发现", "名称": "太湖风波"},
                ])
                self.assertTrue(results[0]["ok"], results)
                runtime = session.quest_state["runtimes"]["太湖风波"]
                self.assertEqual(runtime["lifecycle"], "active")
                self.assertEqual(runtime["completed_node_ids"], ["entry"])
                session.commit()
                self.assertEqual(session.public_notice_results(), [{
                    "ok": True,
                    "msg": "线索【太湖风波】已发现",
                    "变更": "线索【太湖风波】已发现",
                }])
        self.assertEqual(
            [clue["名称"] for clue in explore["任务摘要及进度"]],
            ["太湖风波"],
        )

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
                    {"类型": "线索-发现", "名称": "书房暗痕"},
                ])
                self.assertTrue(results[0]["ok"])
                self.assertTrue(results[0]["_静默"])
                session.commit()
                self.assertEqual(session.public_notice_results(), [])

    def test_multiple_prepared_blueprints_adopt_together(self):
        second_fact = "scene:garden.secret_found@world"
        first = draft_record()
        second = draft_record(
            reward_prefix="garden-secret", fact=second_fact, name="园中暗痕"
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
                     "名称列表": ["园中暗痕", "书房暗痕"]},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                    {"类型": "事实", "事实": second_fact, "值": "found"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                self.assertEqual(
                    [row.get("_quest_name") for row in results[:2]],
                    ["书房暗痕", "园中暗痕"],
                )
                self.assertEqual(set(session.quest_state["definitions"]),
                                 {"书房暗痕", "园中暗痕"})
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
                    {"类型": "线索-采用草稿", "名称列表": [record["quest_name"]]},
                    {"类型": "事实", "事实": EXTENSION_FACT, "值": "follow"},
                ])
                self.assertTrue(all(row["ok"] for row in results), results)
                definition = session.quest_state["definitions"]["书房余波"]
                runtime = session.quest_state["runtimes"]["书房余波"]
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
                    {"类型": "线索-采用草稿", "名称列表": [record["quest_name"]]},
                    {"类型": "事实", "事实": FACT, "值": "found"},
                ])
                runtime = session.quest_state["runtimes"]["书房暗痕"]
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
                    {"类型": "线索-采用草稿", "名称列表": [record["quest_name"]]},
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
                    {"类型": "线索-采用草稿", "名称列表": [record["quest_name"]]},
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
                    {"类型": "线索-采用草稿", "名称列表": [record["quest_name"]]},
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
                    {"类型": "线索-采用草稿", "名称列表": ["书房暗痕"]},
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
                runtime = session.quest_state["runtimes"]["书房暗痕"]
                self.assertTrue(results[0]["_静默"])
                self.assertEqual(runtime["lifecycle"], "hidden")
                self.assertEqual(runtime["completed_node_ids"], [])
                self.assertEqual(explore["任务摘要及进度"], [])
                self.assertEqual(session.public_notice_results(), [])
                public = _public_results(results)
                self.assertFalse(any("书房暗痕" in str(item) for item in public))

    def test_engine_output_keeps_quest_hints_gm_only(self):
        response = {"结算": [{"ok": True, "变更": "体力-1"}]}
        hints = [{"类型": "潜在线索变化", "影响线索": [{"名称": "书房暗痕"}]}]
        result = _attach_quest_hints(response, hints)
        self.assertEqual(result["结算"], [{"ok": True, "变更": "体力-1"}])
        self.assertEqual(result["GM线索提示"], hints)

    def test_create_slot_moves_preset_hints_to_the_settlement_session(self):
        class HintSession:
            def __init__(self):
                self.hints = []

            def add_hints(self, hints):
                self.hints.extend(hints)

        hint = {
            "类型": "隐藏线索", "线索": "太湖水寨之患",
            "入口节点": "entry", "引子": "苏州水路不靖。",
        }
        session = HintSession()
        previous = est._SESSION
        est._SESSION = session
        try:
            with patch("settle.engine_actions.sm._slot_writable", return_value=True), \
                 patch("settle.engine_actions.sm.create_slot", return_value={
                     "slot": 3, "当前位置": "苏州城", "当前时间": 10,
                     "剩余": 5, "GM线索提示": [hint],
                 }), \
                 patch("settle.engine_actions.es.get", return_value="苏州城"), \
                 patch("settle.engine_actions.sc.load_scenes", return_value={}):
                results = _act_create_slot(
                    3, {}, {"角色": {"名称": "试剑人", "装备": {}, "武学": []}}
                )
        finally:
            est._SESSION = previous
        self.assertTrue(results[0]["ok"])
        self.assertEqual(session.hints, [hint])
        response = _attach_quest_hints({"结算": results}, session.hints)
        self.assertEqual(response["GM线索提示"], [hint])
        self.assertNotIn("GM线索提示", response["结算"][0])

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


GATE_FACT = "scene:gate-judge.progress@world"


def gate_blueprint():
    return {
        "名称": "扩展打回", "引子": "打回校验。", "隐藏目标": "验证扩展点打回",
        "事实定义": [{"事实键": GATE_FACT, "描述": "扩展点进度",
                  "值类型": "enum", "可选值": ["idle", "reached", "abandoned"]}],
        "起始节点": ["heard"],
        "节点": [
            {"节点ID": "heard", "关闭条件": None, "关闭描述": None, "完成条件": {},
             "完成摘要": "线索已立。", "后继节点": ["gate", "settled"]},
            {"节点ID": "gate", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
             "完成条件": {"fact": GATE_FACT, "eq": "reached"},
             "完成摘要": "到达扩展点。", "扩展点": True},
            {"节点ID": "settled", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
             "完成条件": {"fact": GATE_FACT, "eq": "abandoned"},
             "完成摘要": "线索就此了结。", "终局": "解决"},
        ],
    }


def gate_character(name="打回校验者"):
    return {
        "名称": name, "阵营": "江湖", "性别": "男", "年岁": 20,
        "武功定位": "武者",
        "品性": {"仁善": 50, "义气": 50, "胆魄": 50, "野心": 0, "底线": 50,
                 "智计": 50, "重利": 0, "守序": 50, "纵欲": 0, "信仰": 0},
        "一级属性": {"根骨": 10, "力道": 10, "身法": 10, "内功": 10},
        "极性": {"根骨": 50, "力道": 50, "身法": 50, "内功": 50},
        "铜钱": 1000, "物品": ["玉佩"], "武学": [],
        "武艺": {"搏击": 10, "剑法": 0, "刀法": 0, "长兵": 0, "奇门": 0, "暗器": 0},
        "技艺": {}, "装备": {},
    }


class JudgeExtensionGateIntegrationTest(unittest.TestCase):
    """judge 扩展点打回端到端：未扩展即到达 → 整体打回且零落盘；prepare+采纳后恢复。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save_dir = self.temp.name
        self.slot = 3

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, command, payload):
        env = {**os.environ, "WUXIA_RPG_SAVE_DIR": self.save_dir}
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "engine.py"), command],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, env=env, timeout=60,
        )
        return json.loads(proc.stdout)

    def _go(self, actions):
        return self._run("go", {"槽位": self.slot, "行为": actions})

    def _judge(self, actions, story):
        return self._run("judge", {"槽位": self.slot, "行为": actions, "当前剧情": story})

    def _slot_file(self, filename):
        path = os.path.join(self.save_dir, f"slot_{self.slot}", filename)
        with open(path, encoding="utf-8") as file:
            return file.read()

    def test_reject_then_recover(self):
        from engine import OPENING_ERA_TEMPLATE

        created = self._go([{"类型": "创建角色", "角色": gate_character()}])
        self.assertIsNone(created.get("错误"), created)
        opened = self._judge([], OPENING_ERA_TEMPLATE + "\n\n打回校验者初入江湖。")
        self.assertIsNone(opened.get("错误"), opened)

        # 轮1：建任务 + 事实 idle（扩展点条件未成立）→ 正常结算
        self.assertIsNone(self._go([{"类型": "其他行为", "描述": "查看四周"}]).get("错误"))
        built = self._judge([
            {"类型": "线索-创建", "任务": gate_blueprint()},
            {"类型": "事实", "事实": GATE_FACT, "值": "idle"},
        ], "线索已立，尚未到达扩展点。")
        self.assertIsNone(built.get("错误"), built)

        # 轮2：事实使扩展点条件成立 → judge 整体打回
        self.assertIsNone(self._go([{"类型": "其他行为", "描述": "继续查探"}]).get("错误"))
        before = {
            name: self._slot_file(name)
            for name in ("world_facts.json", "quest_state.json", "explore.json",
                         os.path.join(".runtime", "turn_state.json"))
        }
        rejected = self._judge(
            [{"类型": "事实-修订", "事实": GATE_FACT, "值": "reached", "原因": "追查有新进展。"}],
            "行进至扩展点。")
        self.assertIn("扩展点", rejected.get("错误") or "")
        self.assertIn("打回", rejected.get("错误") or "")
        # 原子性：世界事实 / 任务状态 / 游历 / 回合状态字节级不变
        for name, content in before.items():
            self.assertEqual(self._slot_file(name), content, name)

        # 恢复：quest-prepare 扩展 → judge 采纳 + 重设事实 → 扩展点亮
        prepared = self._run("quest-prepare", {"槽位": self.slot, "任务": [{
            "操作": "扩展",
            "蓝图": {
                "名称": "扩展打回", "扩展点": "gate", "版本": 2,
                "起始节点": ["after-gate"],
                "节点": [{"节点ID": "after-gate", "关闭条件": None, "关闭描述": None,
                           "前置节点": ["gate"], "完成条件": {},
                           "完成摘要": "扩展后继收束。", "终局": "关闭"}],
            },
        }]})
        self.assertTrue(prepared.get("ok"), prepared)
        recovered = self._judge([
            {"类型": "线索-采用草稿", "名称列表": ["扩展打回"]},
            {"类型": "事实-修订", "事实": GATE_FACT, "值": "reached", "原因": "追查有新进展。"},
        ], "扩展后继收束。")
        self.assertIsNone(recovered.get("错误"), recovered)
        quest_state = json.loads(self._slot_file("quest_state.json"))
        runtime = quest_state["runtimes"]["扩展打回"]
        self.assertEqual(quest_state["definitions"]["扩展打回"]["version"], 2)
        for node_id in ("gate", "after-gate"):
            self.assertIn(node_id, runtime["completed_node_ids"])


if __name__ == "__main__":
    unittest.main()
