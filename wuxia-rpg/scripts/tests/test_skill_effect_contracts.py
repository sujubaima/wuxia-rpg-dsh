#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""代表性技能特效的目标、状态、层数、时长与附加字段契约。"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import battle_engine as be
from common import status_manager as sm


def make_char(name="甲", team="我方"):
    attrs = {
        "气血上限": 5000, "内力上限": 2000,
        "攻击力": 150, "防御力": 120, "精准": 120, "识破": 120,
        "暴击": 80, "速度": 100,
        "力道": 30, "根骨": 30, "内功": 30, "身法": 30,
        "休息气血恢复": 0, "休息内力恢复": 0.1,
    }
    return {
        "名称": name, "阵营": team, "气血": 5000, "内力": 1500,
        "状态效果": [], "二级属性": attrs,
        "一级属性": {"力道": 30, "根骨": 30, "内功": 30, "身法": 30},
        "武艺": {"剑法": 10, "刀法": 10, "长兵": 10,
                 "奇门": 10, "暗器": 10, "搏击": 10},
        "冷却": {}, "充能": 0, "武学": [], "装备": {}, "物品": [],
    }


def status_rows(char):
    return [(e["id"], e["剩余时间"]) for e in char["状态效果"]]


class SkillStatusContractTest(unittest.TestCase):
    CASES = (
        {
            "skill": "兰阳剑法", "stages": ("on_target_resolved",),
            "expected": {"甲": [("huichun", 2)]},
        },
        {
            "skill": "仁剑义剑",
            "stages": ("on_target_confirmed", "on_target_resolved"),
            "expected": {"乙": [("qiangming", 2), ("po_fang", 2)]},
        },
        {
            "skill": "同归剑法", "stages": ("on_target_resolved",),
            "expected": {"甲": [("reflect_damage", 3)]},
        },
        {
            "skill": "太极剑意", "stages": ("on_target_resolved",),
            "expected": {"乙": [("xuhao", 2), ("xuhao", 2)]},
        },
        {
            "skill": "天道三垣剑", "stages": ("on_target_resolved",),
            "expected": {
                "甲": [("insightful", 2), ("insightful", 2)],
                "友": [("insightful", 1), ("insightful", 1)],
            },
        },
        {
            "skill": "长空神剑", "stages": ("on_target_resolved",),
            "expected": {"乙": [("fengji", 2)]},
            "extra": {"乙": {"fengji": {"封禁品级": [2, 3]}}},
        },
        {
            "skill": "秘法钉头箭", "stages": ("on_target_resolved",),
            "expected": {"乙": [("wugu", 7)]},
            "extra": {"乙": {"wugu": {"削减比例": 0.07}}},
        },
        {
            "skill": "鬼火书", "stages": ("on_target_resolved",),
            "expected": {"乙": [("fenshen", 2)]},
            "extra": {"乙": {"fenshen": {"武学等级": 1}}},
        },
    )

    def test_status_applying_skill_contracts(self):
        skills = be.load_skills()
        for case in self.CASES:
            with self.subTest(skill=case["skill"]):
                actor = make_char()
                ally = make_char("友")
                target = make_char("乙", "敌方")
                characters = [actor, ally, target]
                skill = dict(skills.get(case["skill"]), _等级=1)
                source = be.make_action_source(actor, skill)
                self.assertIsNotNone(source)
                result = {}
                ctx = be.make_combat_context(actor, skill, result, characters, target,
                                             action_source=source, effect_triggered=True,
                                             insight={"类型": "无", "发动": True})
                for stage in case["stages"]:
                    ctx["事件"] = {"事件": stage, "攻击方": actor,
                                   "目标": target, "武学": skill}
                    be.dispatch_combat_stage(stage, ctx, source)

                by_name = {c["名称"]: c for c in characters}
                for name, expected in case["expected"].items():
                    self.assertEqual(status_rows(by_name[name]), expected)
                expected_total = sum(len(rows) for rows in case["expected"].values())
                self.assertEqual(len(result.get("施加状态", [])), expected_total)
                for name, by_status in case.get("extra", {}).items():
                    for status_id, fields in by_status.items():
                        entry = next(e for e in by_name[name]["状态效果"]
                                     if e["id"] == status_id)
                        for key, value in fields.items():
                            self.assertEqual(entry[key], value)


class SkillFinisherContractTest(unittest.TestCase):
    def _context(self, target_hp=500, level=1):
        skills = be.load_skills()
        actor = make_char()
        actor["充能"] = 0
        target = make_char("乙", "敌方")
        target["气血"] = target_hp
        skill = dict(skills.get("斩邪雌雄剑"), _等级=level)
        source = be.make_action_source(actor, skill)
        result = {}
        ctx = be.make_combat_context(actor, skill, result, [actor, target], target,
                                     action_source=source, effect_triggered=True,
                                     insight={"类型": "独立", "发动": True})
        return actor, target, skill, source, result, ctx

    def test_zhanxie_pushes_self_sequence_on_lethal_skill_damage(self):
        actor, target, skill, source, result, ctx = self._context()
        ctx["事件"] = {"事件": "伤害", "攻击方": actor, "目标": target,
                       "来源": skill["名称"], "实际落气血": 500}

        be.dispatch_combat_stage("on_damage_resolved", ctx, source)

        self.assertEqual(actor["充能"], 100)
        self.assertEqual(result["时序变化"][0]["变化"], 100)

    def test_zhanxie_max_level_pushes_150_sequence(self):
        actor, target, skill, source, result, ctx = self._context(level=10)
        ctx["事件"] = {"事件": "伤害", "攻击方": actor, "目标": target,
                       "来源": skill["名称"], "实际落气血": 500}

        be.dispatch_combat_stage("on_damage_resolved", ctx, source)

        self.assertEqual(actor["充能"], 150)
        self.assertEqual(result["时序变化"][0]["变化"], 150)

    def test_zhanxie_does_not_trigger_on_nonlethal_or_other_damage(self):
        actor, target, skill, source, result, ctx = self._context()
        ctx["事件"] = {"事件": "伤害", "攻击方": actor, "目标": target,
                       "来源": skill["名称"], "实际落气血": 499}
        be.dispatch_combat_stage("on_damage_resolved", ctx, source)
        self.assertEqual(actor["充能"], 0)
        self.assertNotIn("时序变化", result)

        ctx["事件"]["实际落气血"] = 500
        ctx["事件"]["来源"] = "反伤"
        be.dispatch_combat_stage("on_damage_resolved", ctx, source)
        self.assertEqual(actor["充能"], 0)


class SkillInsightContractTest(unittest.TestCase):
    def test_renyi_and_tonggui_use_independent_insight(self):
        skills = be.load_skills()
        self.assertEqual(skills.get("仁剑义剑").get("识破类型"), "独立")
        self.assertEqual(skills.get("同归剑法").get("识破类型"), "独立")

    def test_tonggui_reflect_is_gated_by_target_insight(self):
        skills = be.load_skills()
        actor = make_char()
        target = make_char("乙", "敌方")
        characters = [actor, target]
        skill = dict(skills.get("同归剑法"), _等级=1)
        source = be.make_action_source(actor, skill)
        ctx = be.make_combat_context(actor, skill, {}, characters, target,
                                     action_source=source, effect_triggered=False,
                                     insight={"类型": "独立", "发动": False})
        be.dispatch_combat_stage("on_target_resolved", ctx, source)
        self.assertEqual(actor["状态效果"], [])


class SkillTransferContractTest(unittest.TestCase):
    def _context(self):
        skills = be.load_skills()
        actor = make_char()
        target = make_char("乙", "敌方")
        characters = [actor, target]
        skill = dict(skills.get("玉女素心剑"), _等级=1)
        source = be.make_action_source(actor, skill)
        result = {}
        ctx = be.make_combat_context(actor, skill, result, characters, target,
                                     action_source=source, effect_triggered=True,
                                     insight={"类型": "无", "发动": True})
        ctx["事件"] = {"事件": "目标结算", "攻击方": actor,
                       "目标": target, "武学": skill}
        return actor, target, source, result, ctx

    def test_yunv_randomly_transfers_one_negative_status(self):
        actor, target, source, result, ctx = self._context()
        sm.apply_status(actor, "broken_tendon", 3, extra={"自定义": "保留"})
        sm.apply_status(actor, "xuhao", -1)
        sm.apply_status(actor, "xiao_zhoutian", 4)
        chosen = next(e for e in actor["状态效果"] if e["id"] == "broken_tendon")

        with patch.object(source["模块"].random, "choice", return_value=chosen) as choice:
            be.dispatch_combat_stage("on_target_resolved", ctx, source)

        candidates = choice.call_args.args[0]
        self.assertEqual({e["id"] for e in candidates}, {"broken_tendon", "xuhao"})
        self.assertEqual([e["id"] for e in actor["状态效果"]],
                         ["xuhao", "xiao_zhoutian"])
        moved = target["状态效果"][0]
        self.assertEqual((moved["id"], moved["剩余时间"]), ("broken_tendon", 3))
        self.assertEqual(moved["自定义"], "保留")
        self.assertEqual(result["状态转移"][0]["转移目标"], "乙")

    def test_yunv_has_no_effect_without_negative_status(self):
        actor, target, source, result, ctx = self._context()
        sm.apply_status(actor, "xiao_zhoutian", 4)

        be.dispatch_combat_stage("on_target_resolved", ctx, source)

        self.assertEqual([e["id"] for e in actor["状态效果"]], ["xiao_zhoutian"])
        self.assertEqual(target["状态效果"], [])
        self.assertNotIn("状态转移", result)

    def test_yunv_uses_independent_insight(self):
        skill = be.load_skills().get("玉女素心剑")
        self.assertEqual(skill.get("识破类型"), "独立")


class SkillCooldownContractTest(unittest.TestCase):
    def test_jiugong_random_skill_enters_or_extends_cooldown(self):
        skills = be.load_skills()
        actor = make_char()
        target = make_char("乙", "敌方")
        target["携带技能"] = ["同归剑法", "太岳剑法"]
        characters = [actor, target]
        skill = dict(skills.get("九宫八卦剑"), _等级=1)
        source = be.make_action_source(actor, skill)
        result = {}
        ctx = be.make_combat_context(actor, skill, result, characters, target,
                                     action_source=source, effect_triggered=True,
                                     insight={"类型": "独立", "发动": True})
        ctx["事件"] = {"事件": "目标结算", "攻击方": actor,
                       "目标": target, "武学": skill}

        with patch.object(source["模块"].random, "choice", return_value="同归剑法"):
            be.dispatch_combat_stage("on_target_resolved", ctx, source)
            self.assertEqual(target["冷却"]["同归剑法"], 2)
            first = result["冷却变化"][0]
            self.assertTrue(first["新增冷却"])

            result.clear()
            be.dispatch_combat_stage("on_target_resolved", ctx, source)
            self.assertEqual(target["冷却"]["同归剑法"], 3)
            second = result["冷却变化"][0]
            self.assertFalse(second["新增冷却"])
            self.assertEqual((second["原值"], second["新值"]), (2, 3))

    def test_jiugong_has_no_effect_without_active_skills(self):
        skills = be.load_skills()
        actor = make_char()
        target = make_char("乙", "敌方")
        target["携带技能"] = []
        characters = [actor, target]
        skill = dict(skills.get("九宫八卦剑"), _等级=1)
        source = be.make_action_source(actor, skill)
        result = {}
        ctx = be.make_combat_context(actor, skill, result, characters, target,
                                     action_source=source, effect_triggered=True)
        ctx["事件"] = {"事件": "目标结算", "攻击方": actor,
                       "目标": target, "武学": skill}

        be.dispatch_combat_stage("on_target_resolved", ctx, source)

        self.assertEqual(target["冷却"], {})
        self.assertNotIn("冷却变化", result)


if __name__ == "__main__":
    unittest.main()
