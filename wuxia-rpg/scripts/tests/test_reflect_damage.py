#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【反伤】状态的伤害结算、叠层、交互与战报回归。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import battle as report
from combat import battle_engine as be


def make_char(name="甲", team="我方", hp=500, mp=500):
    attrs = {
        "气血上限": 500, "内力上限": 500,
        "攻击力": 100, "防御力": 100, "精准": 100, "识破": 100,
        "暴击": 100, "速度": 100,
        "力道": 20, "根骨": 20, "内功": 20, "身法": 20,
        "休息气血恢复": 0, "休息内力恢复": 0.1,
    }
    return {
        "名称": name, "阵营": team, "气血": hp, "内力": mp,
        "状态效果": [], "二级属性": attrs,
        "一级属性": {"力道": 20, "根骨": 20, "内功": 20, "身法": 20},
        "武艺": {"剑法": 10}, "冷却": {}, "充能": 0,
        "武学": [], "装备": {}, "物品": [],
    }


def reflect_entry():
    return {"id": "reflect_damage", "剩余时间": 2, "场景": "战斗"}


def skill_context(attacker, target, characters, result=None):
    skill = {"名称": "测试剑法", "类型": "剑法", "威力倍率": 1.0}
    event = {
        "事件": "伤害", "攻击方": attacker, "目标": target,
        "原目标": target, "落气血": 100, "落内力": 0, "来源": skill["名称"],
    }
    result = result if result is not None else {}
    ctx = be.make_combat_context(attacker, skill, result, characters, target, event)
    return event, ctx, result


class ReflectDamageSettlementTest(unittest.TestCase):
    def test_single_and_multiple_stacks_add_twenty_percent_each(self):
        for stacks, expected in ((1, 20), (2, 40), (3, 60)):
            with self.subTest(stacks=stacks):
                attacker = make_char()
                target = make_char("乙", "敌方")
                for _ in range(stacks):
                    be.apply_status(target, "reflect_damage", 2)
                self.assertEqual(len(target["状态效果"]), stacks)
                characters = [attacker, target]
                event, ctx, result = skill_context(attacker, target, characters)

                be.settle(characters, event, ctx=ctx)

                self.assertEqual(target["气血"], 400)
                self.assertEqual(attacker["气血"], 500 - expected)
                reflected = result["反伤结算"]
                self.assertEqual(reflected["层数"], stacks)
                self.assertEqual(reflected["伤害"], expected)

    def test_reflects_actual_damage_after_qiangming_and_on_lethal_hit(self):
        attacker = make_char()
        target = make_char("乙", "敌方", hp=50)
        target["状态效果"] = [reflect_entry(), {
            "id": "qiangming", "剩余时间": 2, "场景": "战斗",
        }]
        characters = [attacker, target]
        event, ctx, result = skill_context(attacker, target, characters)

        be.settle(characters, event, ctx=ctx)

        self.assertEqual(target["气血"], 1)
        self.assertEqual(attacker["气血"], 490)
        self.assertEqual(result["反伤结算"]["伤害"], 10)

        attacker = make_char()
        target = make_char("乙", "敌方", hp=50)
        target["状态效果"] = [reflect_entry()]
        characters = [attacker, target]
        event, ctx, result = skill_context(attacker, target, characters)
        be.settle(characters, event, ctx=ctx)
        self.assertEqual(target["气血"], 0)
        self.assertEqual(attacker["气血"], 490)
        self.assertEqual(result["反伤结算"]["伤害"], 10)

    def test_zero_damage_does_not_reflect_and_reflected_damage_can_be_blocked(self):
        attacker = make_char()
        target = make_char("乙", "敌方")
        target["状态效果"] = [reflect_entry(), {
            "id": "bati", "剩余时间": 2, "场景": "战斗",
        }]
        characters = [attacker, target]
        event, ctx, result = skill_context(attacker, target, characters)
        be.settle(characters, event, ctx=ctx)
        self.assertEqual(target["气血"], 500)
        self.assertEqual(attacker["气血"], 500)
        self.assertNotIn("反伤结算", result)

        attacker = make_char()
        attacker["状态效果"] = [{"id": "bati", "剩余时间": 2, "场景": "战斗"}]
        target = make_char("乙", "敌方")
        target["状态效果"] = [reflect_entry()]
        characters = [attacker, target]
        event, ctx, result = skill_context(attacker, target, characters)
        be.settle(characters, event, ctx=ctx)
        self.assertEqual(attacker["气血"], 500)
        self.assertEqual(result["反伤结算"]["伤害"], 0)
        self.assertEqual(result["反伤结算"]["霸体抵挡"]["名称"], "霸体")

    def test_reflected_damage_does_not_chain_or_feed_fenshen(self):
        attacker = make_char()
        attacker["状态效果"] = [reflect_entry()]
        target = make_char("乙", "敌方")
        target["状态效果"] = [reflect_entry(), {
            "id": "fenshen", "剩余时间": 2, "场景": "战斗", "武学等级": 1,
        }]
        characters = [attacker, target]
        event, ctx, result = skill_context(attacker, target, characters)

        be.settle(characters, event, ctx=ctx)

        self.assertEqual(target["气血"], 400)
        self.assertEqual(attacker["气血"], 480)
        self.assertEqual(target.get("_焚身蓄", 0), 0)
        self.assertEqual(result["反伤结算"]["伤害"], 20)

    def test_non_skill_damage_does_not_trigger(self):
        attacker = make_char()
        target = make_char("乙", "敌方")
        target["状态效果"] = [reflect_entry()]
        characters = [attacker, target]
        event = {
            "事件": "伤害", "攻击方": attacker, "目标": target,
            "落气血": 100, "落内力": 0, "来源": "机关",
        }
        result = {}
        ctx = be.make_combat_context(attacker, None, result, characters, target, event)

        be.settle(characters, event, ctx=ctx)

        self.assertEqual(target["气血"], 400)
        self.assertEqual(attacker["气血"], 500)
        self.assertNotIn("反伤结算", result)


class ReflectDamageReportTest(unittest.TestCase):
    def test_reflect_result_is_visible_and_structured(self):
        result = {
            "行动者": "甲", "指令": "武学", "技能": "九宫八卦剑", "目标": "乙",
            "闪避": False, "暴击": False, "伤害": 100,
            "行动者内力变化": {"原值": 500, "新值": 410},
            "目标气血变化": {"原值": 500, "新值": 400},
            "反伤结算": {
                "来源": "反伤", "目标": "甲", "层数": 1, "伤害": 20,
                "原值": 500, "新值": 480, "内力原值": 410, "内力新值": 410,
                "击败": False,
            },
        }

        text = report.render_turn(1, result, be.load_skills())
        self.assertIn("【反伤】震返20点伤害予甲", text)
        self.assertIn("气血 500→480", text)
        structured = report.struct_turn_entry(1, result, skills_db=be.load_skills())
        self.assertEqual(structured["反伤结算"]["伤害"], 20)


if __name__ == "__main__":
    unittest.main()
