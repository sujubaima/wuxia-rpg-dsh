#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预设故事线目录、静态入口链和真实资源完整性。"""
import json
import re
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
PROJECT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common.json_io import JsonReadError  # noqa: E402
from quest.engine import (discover_quest, extend_quest,  # noqa: E402
                          potential_progress_hints, reduce_affected_quests)
from quest.presets import build_initial_preset_state, load_preset_blueprints  # noqa: E402
from quest.projection import project_clues  # noqa: E402
from quest.world_facts import fact_key_parts, upsert_fact  # noqa: E402

DATA_DIR = PROJECT / "assets" / "data"
QUESTS = DATA_DIR / "quests"
STORYLINES = PROJECT / "references" / "wuxia-rpg-storylines.md"


def preset_blueprint(name="测试故事", region="苏州城", shared_definition=None):
    owner = f"test-{name}"
    outcome = f"quest:{owner}.outcome@world"
    resolved_choice = f"choice:{owner}:accepted.selected@world"
    closed_choice = f"choice:{owner}:declined.selected@world"
    definitions = [
        shared_definition or {
            "事实键": "player.region@world",
            "描述": "玩家当前所在的大区域",
            "值类型": "string",
            "修订策略": "free",
        },
        {
            "事实键": outcome,
            "描述": f"故事线【{name}】最终走向",
            "值类型": "enum",
            "可选值": ["resolved", "closed"],
        },
        {
            "事实键": resolved_choice,
            "描述": f"已明确选择解决故事线【{name}】",
            "值类型": "bool",
        },
        {
            "事实键": closed_choice,
            "描述": f"已明确选择关闭故事线【{name}】",
            "值类型": "bool",
        },
    ]
    return {
        "版本": 1,
        "名称": name,
        "引子": f"{name}的引子。",
        "隐藏目标": f"查明{name}的真相。",
        "起始节点": ["entry"],
        "事实定义": definitions,
        "节点": [
            {
                "节点ID": "entry",
                "完成条件": {"fact": "player.region@world", "eq": region},
                "完成摘要": f"听闻{name}。",
                "关闭条件": None,
                "关闭描述": None,
                "后继节点": ["resolved", "closed", "follow-up"],
            },
            {
                "节点ID": "follow-up",
                "前置节点": ["entry"],
                "完成条件": {"node": "entry", "completed": True},
                "完成摘要": f"{name}或有后续。",
                "关闭条件": None,
                "关闭描述": None,
                "扩展点": True,
            },
            {
                "节点ID": "resolved",
                "前置节点": ["entry"],
                "完成条件": {"fact": resolved_choice, "eq": True},
                "完成摘要": f"{name}已经解决。",
                "关闭条件": None,
                "关闭描述": None,
                "终局": True,
                "效果": [{
                    "类型": "事实-写入", "事实": outcome,
                    "值": "resolved", "状态": "verified",
                }],
            },
            {
                "节点ID": "closed",
                "前置节点": ["entry"],
                "完成条件": {"fact": closed_choice, "eq": True},
                "完成摘要": f"{name}已经关闭。",
                "关闭条件": None,
                "关闭描述": None,
                "终局": True,
                "效果": [{
                    "类型": "事实-写入", "事实": outcome,
                    "值": "closed", "状态": "verified",
                }],
            },
        ],
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class PresetDirectoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.quest_dir = self.data_dir / "quests"

    def tearDown(self):
        self.temp.cleanup()

    def test_flat_files_load_in_filename_order(self):
        write_json(self.quest_dir / "乙.json", preset_blueprint("乙线"))
        write_json(self.quest_dir / "甲.json", preset_blueprint("甲线"))
        loaded = load_preset_blueprints(self.data_dir)
        self.assertEqual([path.name for path, _raw in loaded], ["乙.json", "甲.json"])

    def test_missing_empty_and_nested_directories_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "目录不存在"):
            load_preset_blueprints(self.data_dir)

        self.quest_dir.mkdir()
        with self.assertRaisesRegex(ValueError, "目录为空"):
            load_preset_blueprints(self.data_dir)

        nested = self.quest_dir / "草稿"
        nested.mkdir()
        write_json(nested / "不应扫描.json", preset_blueprint())
        with self.assertRaisesRegex(ValueError, "不得包含子目录.*草稿"):
            load_preset_blueprints(self.data_dir)

    def test_malformed_and_non_object_json_report_the_file(self):
        self.quest_dir.mkdir()
        malformed = self.quest_dir / "坏语法.json"
        malformed.write_text("{", encoding="utf-8")
        with self.assertRaises(JsonReadError) as caught:
            load_preset_blueprints(self.data_dir)
        self.assertIn("坏语法.json", str(caught.exception))

        malformed.unlink()
        write_json(self.quest_dir / "非对象.json", [])
        with self.assertRaises(JsonReadError) as caught:
            load_preset_blueprints(self.data_dir)
        self.assertIn("非对象.json", str(caught.exception))

    def test_duplicate_names_and_inconsistent_shared_definitions_fail(self):
        write_json(self.quest_dir / "一.json", preset_blueprint("同名线"))
        write_json(self.quest_dir / "二.json", preset_blueprint("同名线"))
        with self.assertRaisesRegex(ValueError, "二.json.*已存在"):
            build_initial_preset_state(
                self.data_dir, {"名称": "测试者"}, {"当前位置": "苏州城"}
            )

        for path in self.quest_dir.glob("*.json"):
            path.unlink()
        write_json(self.quest_dir / "一.json", preset_blueprint("甲线"))
        conflicting = {
            "事实键": "player.region@world",
            "描述": "玩家当前所在的大区域",
            "值类型": "string",
            "修订策略": "explicit",
        }
        write_json(
            self.quest_dir / "二.json",
            preset_blueprint("乙线", shared_definition=conflicting),
        )
        with self.assertRaisesRegex(ValueError, "二.json.*定义不一致"):
            build_initial_preset_state(
                self.data_dir, {"名称": "测试者"}, {"当前位置": "苏州城"}
            )

    def test_circular_unlock_chain_without_mechanical_anchor_fails(self):
        def circular(name, entry_fact, produced_fact):
            raw = preset_blueprint(name)
            raw["事实定义"][0] = {
                "事实键": entry_fact,
                "描述": f"入口事实【{entry_fact}】",
                "值类型": "bool",
                "修订策略": "free",
            }
            raw["事实定义"].append({
                "事实键": produced_fact,
                "描述": f"入口事实【{produced_fact}】",
                "值类型": "bool",
                "修订策略": "free",
            })
            raw["节点"][0]["完成条件"] = {"fact": entry_fact, "eq": True}
            raw["节点"][1]["效果"] = [{
                "类型": "事实-写入", "事实": produced_fact,
                "值": True, "状态": "verified",
            }]
            return raw

        fact_a = "information:cycle-a:entry.discovered@world"
        fact_b = "information:cycle-b:entry.discovered@world"
        write_json(self.quest_dir / "甲.json", circular("循环甲", fact_a, fact_b))
        write_json(self.quest_dir / "乙.json", circular("循环乙", fact_b, fact_a))
        with self.assertRaisesRegex(ValueError, "不可触发入口链.*循环"):
            build_initial_preset_state(
                self.data_dir, {"名称": "测试者"}, {"当前位置": "苏州城"}
            )

    def test_undeclared_empty_and_orphaned_entry_facts_fail(self):
        undeclared = preset_blueprint("漏声明")
        undeclared["事实定义"] = undeclared["事实定义"][1:]
        write_json(self.quest_dir / "漏声明.json", undeclared)
        with self.assertRaisesRegex(ValueError, "漏声明.json.*引用事实未在本任务声明"):
            build_initial_preset_state(
                self.data_dir, {"名称": "测试者"}, {"当前位置": "苏州城"}
            )

        (self.quest_dir / "漏声明.json").unlink()
        empty = preset_blueprint("空入口")
        empty["节点"][0]["完成条件"] = {}
        write_json(self.quest_dir / "空入口.json", empty)
        with self.assertRaisesRegex(ValueError, "空入口.json.*须提供非空完成条件"):
            build_initial_preset_state(
                self.data_dir, {"名称": "测试者"}, {"当前位置": "苏州城"}
            )

        (self.quest_dir / "空入口.json").unlink()
        orphaned = preset_blueprint("孤立入口")
        orphaned["事实定义"][0] = {
            "事实键": "information:orphan:entry.discovered@world",
            "描述": "孤立故事的具体入口信息是否被发现",
            "值类型": "bool",
        }
        orphaned["节点"][0]["完成条件"] = {
            "fact": "information:orphan:entry.discovered@world",
            "eq": True,
        }
        write_json(self.quest_dir / "孤立入口.json", orphaned)
        with self.assertRaisesRegex(ValueError, "无来源入口事实.*orphan"):
            build_initial_preset_state(
                self.data_dir, {"名称": "测试者"}, {"当前位置": "苏州城"}
            )


class RealPresetContentTest(unittest.TestCase):
    def test_all_real_presets_load_hidden_with_empty_player_projection(self):
        result = build_initial_preset_state(
            DATA_DIR,
            {"名称": "试剑人"},
            {"当前位置": "苏州城", "当前时间": 120, "体力": 100},
        )
        quest_state = result["quest_state"]
        self.assertEqual(len(result["loaded"]), 19)
        self.assertEqual(len(quest_state["definitions"]), 19)
        self.assertTrue(all(
            runtime["lifecycle"] == "hidden"
            for runtime in quest_state["runtimes"].values()
        ))
        self.assertEqual(project_clues(quest_state), [])
        self.assertEqual(
            result["world_facts"]["records"]["player.region@world"]["value"],
            "苏州城",
        )
        # 建档未接触任何具体入口事实，不暴露入场提示
        self.assertEqual(result["hints"], [])

    def test_real_bundle_is_independent_of_filesystem_creation_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_data = Path(temporary)
            copied_quests = copied_data / "quests"
            copied_quests.mkdir()
            source = load_preset_blueprints(DATA_DIR)
            for path, raw in reversed(source):
                write_json(copied_quests / path.name, raw)
            original = build_initial_preset_state(
                DATA_DIR, {"名称": "甲"}, {"当前位置": "苏州城"}
            )
            copied = build_initial_preset_state(
                copied_data, {"名称": "甲"}, {"当前位置": "苏州城"}
            )
            self.assertEqual(copied["loaded"], original["loaded"])
            self.assertEqual(copied["quest_state"], original["quest_state"])


class QuestPresetContentTest(unittest.TestCase):
    @staticmethod
    def _raw_bundle():
        return [raw for _path, raw in load_preset_blueprints(DATA_DIR)]

    @staticmethod
    def _walk(condition):
        if not isinstance(condition, dict):
            return
        if "fact" in condition:
            yield condition["fact"]
            return
        for key in ("all", "any"):
            for child in condition.get(key) or []:
                yield from QuestPresetContentTest._walk(child)
        if "not" in condition:
            yield from QuestPresetContentTest._walk(condition["not"])

    def _build(self, region="苏州城"):
        return build_initial_preset_state(
            DATA_DIR,
            {"名称": "试剑人"},
            {"当前位置": region, "当前时间": 0, "体力": 100},
        )

    def _open(self, facts, quests, quest_name="太湖风波", slug="taihu"):
        hook_key = f"information:v3:{slug}:entry.discovered@world"
        upsert_fact(facts, hook_key, True)
        reduce_affected_quests(facts, quests, fact_key=hook_key)
        discover_quest(quests, quest_name)
        reduce_affected_quests(facts, quests, quest_name=quest_name)

    def _set_fact(self, facts, quests, fact_key, value=True):
        upsert_fact(facts, fact_key, value)
        mutations, _events, _notices, _hints = reduce_affected_quests(
            facts, quests, fact_key=fact_key
        )
        for mutation in mutations:
            upsert_fact(
                facts,
                mutation["事实"],
                mutation["值"],
                status=mutation.get("状态", "verified"),
                definition=mutation.get("_定义"),
            )
        return mutations

    def test_directory_is_flat_with_nineteen_tasks(self):
        self.assertTrue(QUESTS.is_dir())
        self.assertFalse((QUESTS / "index.json").exists())
        self.assertFalse(any(path.is_dir() for path in QUESTS.iterdir()))
        self.assertEqual(len(list(QUESTS.glob("*.json"))), 19)
        self.assertFalse((DATA_DIR / "quests_v4").exists())

    def test_bundle_hidden_until_concrete_entry_or_contact(self):
        result = self._build()
        quests = result["quest_state"]
        facts = result["world_facts"]
        self.assertEqual(len(result["loaded"]), 19)
        self.assertTrue(all(
            runtime["lifecycle"] == "hidden"
            for runtime in quests["runtimes"].values()
        ))
        self.assertEqual(project_clues(quests), [])
        self.assertEqual(result["hints"], [])
        hook_key = "information:v3:taihu:entry.discovered@world"
        upsert_fact(facts, hook_key, True)
        reduce_affected_quests(facts, quests, fact_key=hook_key)
        self.assertEqual(
            [hint["线索"] for hint in potential_progress_hints(facts, quests)],
            ["太湖风波"],
        )

    def test_sources_cover_archive_exactly_once(self):
        archive = STORYLINES.read_text(encoding="utf-8")
        archived = [
            re.sub(r"[【】]", "", name).strip()
            for name in re.findall(
                r"^- \*\*(.+?)\*\*：.*$", archive, flags=re.MULTILINE
            )
        ]
        sources = []
        for raw in self._raw_bundle():
            sources.extend(raw.get("来源故事线") or [])
        self.assertEqual(len(archived), 32)
        self.assertEqual(Counter(sources), Counter(archived))
        self.assertTrue(all(count == 1 for count in Counter(sources).values()))

    def test_multi_route_endings_use_choices_then_write_outcome(self):
        for raw in self._raw_bundle():
            name = raw["名称"]
            nodes = raw["节点"]
            by_id = {node["节点ID"]: node for node in nodes}
            self.assertGreaterEqual(len(by_id["entry"]["后继节点"]), 2, name)
            endings = [node for node in nodes if node.get("终局")]
            self.assertGreaterEqual(len(endings), 2, name)
            self.assertTrue(all(node["终局"] is True for node in endings), name)

            choice_keys = set()
            outcome_values = set()
            outcome = next(
                item for item in raw["事实定义"]
                if item["事实键"].endswith(".outcome@world")
            )
            outcome_key = outcome["事实键"]
            for ending in endings:
                choices = {
                    key for key in self._walk(ending["完成条件"])
                    if key.startswith("choice:") and key.endswith(".selected@world")
                }
                self.assertEqual(len(choices), 1, f"{name}:{ending['节点ID']}")
                choice_keys.update(choices)
                outcome_effects = [
                    effect for effect in ending.get("效果") or []
                    if effect.get("类型") == "事实-写入"
                    and effect.get("事实") == outcome_key
                ]
                self.assertEqual(len(outcome_effects), 1, f"{name}:{ending['节点ID']}")
                outcome_values.add(outcome_effects[0]["值"])
            self.assertEqual(len(choice_keys), len(endings), name)
            self.assertEqual(set(outcome["可选值"]), outcome_values, name)

            extensions = [node for node in nodes if node.get("扩展点")]
            self.assertEqual(len(extensions), 1, name)
            self.assertEqual(extensions[0]["后继节点"], [], name)
            for node in nodes:
                self.assertIn("关闭条件", node, name)
                self.assertIn("关闭描述", node, name)
                self.assertTrue(node.get("完成摘要"), name)

    def test_all_bundle_fact_keys_use_the_closed_catalog(self):
        for raw in self._raw_bundle():
            name = raw["名称"]
            defined = {item["事实键"] for item in raw["事实定义"]}
            for key in defined:
                fact_key_parts(key)
            for node in raw["节点"]:
                referenced = set(self._walk(node["完成条件"]))
                referenced.update(self._walk(node.get("关闭条件") or {}))
                self.assertTrue(referenced <= defined, f"{name}:{node['节点ID']}")
                self.assertFalse(any(
                    key.startswith("quest:") and not key.endswith(".outcome@world")
                    for key in referenced
                ), f"{name}:{node['节点ID']}")

    def test_entries_use_only_concrete_information_scene_or_contact_facts(self):
        hook_tasks = set()
        contact_tasks = set()
        for raw in self._raw_bundle():
            name = raw["名称"]
            by_id = {node["节点ID"]: node for node in raw["节点"]}
            entry_facts = set(self._walk(by_id["entry"]["完成条件"]))
            self.assertTrue(entry_facts, name)
            for key in entry_facts:
                _fact_key, subject, predicate, _scope = fact_key_parts(key)
                family = subject.split(":", 1)[0]
                self.assertIn(family, {"character", "information", "scene"}, name)
                if family == "character":
                    self.assertEqual(predicate, "contact", name)
            if any(":entry.discovered@world" in key for key in entry_facts):
                hook_tasks.add(name)
            if any(key.endswith(".contact@player") for key in entry_facts):
                contact_tasks.add(name)
        self.assertEqual(
            contact_tasks,
            {"通天七剑", "黄金颊之谜", "密宗使团", "失魂长生局"},
        )
        self.assertEqual(
            hook_tasks,
            {"太湖风波", "吴门剑怨", "风云盟抉择", "海疆倭患", "禅武之裂",
             "立帮之危", "峨眉青城之争", "华山论剑", "昆仑谍影", "通天七剑",
             "乌衣门之影", "黄金颊之谜", "失魂长生局", "厂卫角力", "迷仙寨用兵",
             "密宗使团", "辽东兵锋"},
        )

    def test_shared_fact_definitions_are_identical(self):
        definitions = {}
        repeated = set()
        for raw in self._raw_bundle():
            for definition in raw["事实定义"]:
                key = definition["事实键"]
                encoded = json.dumps(definition, ensure_ascii=False, sort_keys=True)
                if key in definitions:
                    repeated.add(key)
                    self.assertEqual(encoded, definitions[key], key)
                definitions[key] = encoded
        self.assertTrue(repeated)

    def test_route_progress_resolves_ending_and_unlocks_network(self):
        result = self._build()
        facts = result["world_facts"]
        quests = result["quest_state"]
        self._open(facts, quests)
        for fact_key in (
            "character:v3:taihu:shijinyan.contact@player",
            "document:v3:taihu:official-plan.obtained@world",
        ):
            self._set_fact(facts, quests, fact_key)
        runtime = quests["runtimes"]["太湖风波"]
        self.assertTrue({
            "entry", "meet_shijinyan", "official_plan",
        } <= set(runtime["completed_node_ids"]))
        self._set_fact(
            facts, quests, "choice:v3:taihu:crushed.selected@world"
        )
        runtime = quests["runtimes"]["太湖风波"]
        self.assertEqual(runtime["lifecycle"], "ended")
        self.assertIn("stockade_crushed", runtime["completed_node_ids"])
        self.assertEqual(
            facts["records"]["quest:v3:taihu.outcome@world"]["value"],
            "crushed",
        )
        follow_ups = {
            hint["线索"] for hint in potential_progress_hints(facts, quests)
            if hint["类型"] == "隐藏线索"
        }
        self.assertIn("中原外务网", follow_ups)

    def test_unavailable_route_sources_close_branches_and_task(self):
        result = self._build()
        facts = result["world_facts"]
        quests = result["quest_state"]
        self._open(facts, quests)
        self._set_fact(
            facts, quests, "character:v3:taihu:shijinyan.contact@player"
        )
        self._set_fact(
            facts, quests,
            "information:v3:taihu:route-1-source.available@world", False,
        )
        runtime = quests["runtimes"]["太湖风波"]
        self.assertIn("meet_shijinyan", runtime["completed_node_ids"])
        self.assertIn("official_plan", runtime["closed_node_ids"])
        self.assertNotIn("stockade_crushed", runtime["blocked_node_ids"])
        self.assertEqual(runtime["lifecycle"], "active")
        for index in (2, 3):
            self._set_fact(
                facts, quests,
                f"information:v3:taihu:route-{index}-source.available@world",
                False,
            )
        runtime = quests["runtimes"]["太湖风波"]
        self.assertEqual(runtime["lifecycle"], "ended")
        self.assertTrue(runtime["closed_reason"])

    def test_close_takes_priority_over_completion(self):
        result = self._build()
        facts = result["world_facts"]
        quests = result["quest_state"]
        self._open(facts, quests)
        contact = "character:v3:taihu:shijinyan.contact@player"
        unavailable = "information:v3:taihu:route-1-source.available@world"
        upsert_fact(facts, contact, True)
        upsert_fact(facts, unavailable, False)
        reduce_affected_quests(facts, quests, fact_key=unavailable)
        runtime = quests["runtimes"]["太湖风波"]
        self.assertIn("meet_shijinyan", runtime["closed_node_ids"])
        self.assertNotIn("meet_shijinyan", runtime["completed_node_ids"])

    def test_extension_halt_until_prepared_then_resumes(self):
        result = self._build()
        facts = result["world_facts"]
        quests = result["quest_state"]
        self._open(facts, quests)
        for fact_key in (
            "character:v3:taihu:wanfeipeng.contact@player",
            "information:v3:taihu:knife-lead.discovered@world",
        ):
            self._set_fact(facts, quests, fact_key)
        runtime = quests["runtimes"]["太湖风波"]
        self.assertIn("knife_clue", runtime["completed_node_ids"])
        self.assertNotIn("ext_knife", runtime["completed_node_ids"])
        _mutations, _events, _notices, hints = reduce_affected_quests(
            facts, quests, quest_name="太湖风波"
        )
        self.assertTrue(any(
            hint["类型"] == "任务扩展" and hint["扩展点"] == "ext_knife"
            for hint in hints
        ))
        completion = "document:v3:taihu:completed-knife-manual.obtained@world"
        extend_quest(facts, quests, {
            "名称": "太湖风波",
            "扩展点": "ext_knife",
            "版本": 2,
            "起始节点": ["knife_perfect"],
            "节点": [{
                "节点ID": "knife_perfect",
                "前置节点": [],
                "完成条件": {"fact": completion, "eq": True},
                "完成摘要": "万飞鹏补全刀谱，残刀重光。",
                "关闭条件": None,
                "关闭描述": None,
                "终局": True,
            }],
            "事实定义": [{
                "事实键": completion,
                "描述": "万飞鹏已经取得补全后的具体刀谱",
                "值类型": "bool",
                "修订策略": "explicit",
            }],
        })
        self._set_fact(facts, quests, completion)
        runtime = quests["runtimes"]["太湖风波"]
        self.assertIn("ext_knife", runtime["completed_node_ids"])
        self.assertIn("knife_perfect", runtime["completed_node_ids"])
        self.assertEqual(runtime["lifecycle"], "ended")
        self.assertEqual(runtime["definition_version"], 2)


if __name__ == "__main__":
    unittest.main()
