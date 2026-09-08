#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公开行动入口、AOE、治疗和过滤门禁回归。"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import battle_engine as be
from common import status_manager as sm


SWORD = "八面玉具剑"
POLEARM = "玄铁长枪"


def make_char(name="甲", team="我方", hp=5000, mp=1000):
    attrs = {
        "气血上限": 5000, "内力上限": 2000,
        "攻击力": 150, "防御力": 120, "精准": 120, "识破": 120,
        "暴击": 80, "速度": 100,
        "力道": 30, "根骨": 30, "内功": 30, "身法": 30,
        "休息气血恢复": 0, "休息内力恢复": 0.1,
    }
    return {
        "名称": name, "阵营": team, "气血": hp, "内力": mp,
        "状态效果": [], "二级属性": attrs,
        "一级属性": {"力道": 30, "根骨": 30, "内功": 30, "身法": 30},
        "武艺": {"剑法": 10, "刀法": 10, "长兵": 10,
                 "奇门": 10, "暗器": 10, "搏击": 10},
        "武学": [], "冷却": {}, "充能": 0, "装备": {}, "物品": [],
    }


def deterministic_roll(a, b):
    return 1.0 if b <= 1.05 else 99


def skill_action(skill, target):
    return {"类型": "武学", "技能": skill, "目标": target["名称"]}


class PublicActionIntegrationTest(unittest.TestCase):
    def test_single_attack_pays_cost_and_records_damage(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        skill = be.load_skills().get("太祖长拳")
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            result = be.execute_action(actor, skill_action(skill, target), [actor, target])
        self.assertNotIn("错误", result)
        self.assertEqual(actor["内力"], 940)
        self.assertEqual(result["行动者内力变化"], {"原值": 1000, "新值": 940})
        self.assertGreater(result["伤害"], 0)
        self.assertEqual(target["气血"], result["目标剩余气血"])
        self.assertNotIn(skill["名称"], actor["冷却"])

    def test_weapon_error_and_cooldown_do_not_consume_cost(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        skill = be.load_skills().get("仁剑义剑")
        result = be.execute_action(actor, skill_action(skill, target), [actor, target])
        self.assertIn("未装备剑", result["错误"])
        self.assertEqual(actor["内力"], 1000)

        actor["装备"] = {"武器1": SWORD}
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            result = be.execute_action(actor, skill_action(skill, target), [actor, target])
        self.assertNotIn("错误", result)
        self.assertEqual(actor["内力"], 880)
        self.assertEqual(actor["冷却"][skill["名称"]], 3)

        mp_before = actor["内力"]
        result = be.execute_action(actor, skill_action(skill, target), [actor, target])
        self.assertIn("技能冷却中", result["错误"])
        self.assertEqual(actor["内力"], mp_before)

    def test_shared_aoe_runs_once_and_settles_each_target(self):
        actor = make_char()
        actor["装备"] = {"武器1": POLEARM}
        targets = [make_char("乙", "敌方"), make_char("丙", "敌方")]
        skill = be.load_skills().get("打狗棒法")
        rolls = [1, 99, 99, 1.0, 99, 99, 1.0]
        with patch.object(be.random, "uniform", side_effect=rolls):
            result = be.execute_action(actor, {"类型": "武学", "技能": skill,
                                               "目标": "敌方全体"}, [actor, *targets])
        self.assertNotIn("错误", result)
        self.assertTrue(result["特效发动"])
        self.assertEqual(actor["内力"], 714)
        self.assertEqual(actor["冷却"][skill["名称"]], 4)
        self.assertEqual(len(result["目标结算"]), 2)
        self.assertEqual({row["目标"] for row in result["目标结算"]}, {"乙", "丙"})
        self.assertEqual(sum(e["id"] == "bati" for e in actor["状态效果"]), 2)

    def test_shared_aoe_insight_failure_blocks_only_action_effect(self):
        actor = make_char()
        actor["装备"] = {"武器1": POLEARM}
        targets = [make_char("乙", "敌方"), make_char("丙", "敌方")]
        skill = be.load_skills().get("打狗棒法")
        rolls = [99, 99, 99, 1.0, 99, 99, 1.0]
        with patch.object(be.random, "uniform", side_effect=rolls):
            result = be.execute_action(actor, {"类型": "武学", "技能": skill,
                                               "目标": "敌方全体"}, [actor, *targets])
        self.assertFalse(result["特效发动"])
        self.assertFalse(any(e["id"] == "bati" for e in actor["状态效果"]))
        self.assertTrue(all(row["伤害"] > 0 for row in result["目标结算"]))

    def test_healing_skill_uses_public_cost_cooldown_and_settlement(self):
        actor = make_char()
        actor["装备"] = {"武器1": SWORD}
        ally = make_char("乙", "我方", hp=1000)
        skill = be.load_skills().get("龙华剑术")
        with patch.object(be.random, "uniform", side_effect=[99, 1.0]):
            result = be.execute_action(actor, skill_action(skill, ally), [actor, ally])
        self.assertNotIn("错误", result)
        self.assertEqual(actor["内力"], 880)
        self.assertEqual(actor["冷却"][skill["名称"]], 3)
        self.assertGreater(result["恢复气血"], 0)
        self.assertGreater(ally["气血"], 1000)

    def test_invalid_target_does_not_consume_resources(self):
        actor = make_char()
        skill = be.load_skills().get("太祖长拳")
        result = be.execute_action(actor, {"类型": "武学", "技能": skill,
                                           "目标": "不存在"}, [actor])
        self.assertEqual(result["错误"], "目标无效或已败阵")
        self.assertEqual(actor["内力"], 1000)
        self.assertEqual(actor["冷却"], {})


class FilterAndModifierTest(unittest.TestCase):
    def test_fengxue_blocks_skill_and_item_without_consuming(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        sm.apply_status(actor, "fengxue", 2)
        skill = be.load_skills().get("太祖长拳")
        result = be.execute_action(actor, skill_action(skill, target), [actor, target])
        self.assertIn("武学被封禁", result["错误"])
        self.assertEqual(actor["内力"], 1000)

        item = be.load_items()["小还丹"]
        actor["物品"] = ["小还丹"]
        actor["物品可用次数"] = {"小还丹": 1}
        result = be.execute_action(actor, {"类型": "物品", "物品": item,
                                           "目标": actor["名称"]}, [actor, target])
        self.assertIn("无法使用物品", result["错误"])
        self.assertEqual(actor["物品"], ["小还丹"])
        self.assertEqual(actor["物品可用次数"]["小还丹"], 1)

    def test_fengji_blocks_only_configured_tiers(self):
        actor = make_char()
        sm.apply_status(actor, "fengji", 2, extra={"封禁品级": [2, 3]})
        self.assertFalse(be.skill_available(actor, be.load_skills().get("仁剑义剑")))
        self.assertTrue(be.skill_available(actor, be.load_skills().get("太祖长拳")))
        entry = actor["状态效果"][0]
        entry["封禁品级"] = [1, 2, 3]
        self.assertFalse(be.skill_available(actor, be.load_skills().get("阴阳错剑")))

    def test_sangong_temporarily_filters_heart_method_status(self):
        char = make_char()
        sm.apply_status(char, "iron_wall", -1, source="测试心法", source_type="心法")
        boosted = be.status_attr(char, "防御力")
        self.assertGreater(boosted, 120)
        sm.apply_status(char, "sangong", 2)
        self.assertEqual(be.status_attr(char, "防御力"), 120)
        sangong = next(e for e in char["状态效果"] if e["id"] == "sangong")
        sm.remove_status(char, sangong)
        self.assertEqual(be.status_attr(char, "防御力"), boosted)

    def test_renjian_allows_sword_skill_without_weapon(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        sm.apply_status(actor, "ren_jian_he_yi", -1)
        skill = be.load_skills().get("仁剑义剑")
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            result = be.execute_action(actor, skill_action(skill, target), [actor, target])
        self.assertNotIn("错误", result)
        self.assertEqual(actor["内力"], 880)

    def test_xuhao_stacks_additively_and_zixia_reduces_cooldown(self):
        actor = make_char(mp=1000)
        target = make_char("乙", "敌方")
        actor["装备"] = {"武器1": SWORD}
        sm.apply_status(actor, "xuhao", 2)
        sm.apply_status(actor, "xuhao", 2)
        sm.apply_status(actor, "zixia_jianqi", -1)
        skill = be.load_skills().get("仁剑义剑")
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            result = be.execute_action(actor, skill_action(skill, target), [actor, target])
        self.assertNotIn("错误", result)
        self.assertEqual(actor["内力"], 760)
        self.assertEqual(actor["冷却"][skill["名称"]], 2)

    def test_ethereal_blocks_single_target_but_not_current_aoe_behavior(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        sm.apply_status(target, "ethereal", 2)
        skill = be.load_skills().get("太祖长拳")
        result = be.execute_action(actor, skill_action(skill, target), [actor, target])
        self.assertIn("缥缈虚无", result["错误"])

        actor = make_char()
        actor["装备"] = {"武器1": POLEARM}
        other = make_char("丙", "敌方")
        skill = be.load_skills().get("打狗棒法")
        rolls = [1, 99, 99, 1.0, 99, 99, 1.0]
        with patch.object(be.random, "uniform", side_effect=rolls):
            result = be.execute_action(actor, {"类型": "武学", "技能": skill,
                                               "目标": "敌方全体"}, [actor, target, other])
        self.assertEqual({row["目标"] for row in result["目标结算"]}, {"乙", "丙"})

    def test_ethereal_blocks_enemy_thrown_item_but_not_healing(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        sm.apply_status(target, "ethereal", 2)
        item = be.load_items()["爆竹"]
        actor["物品"] = ["爆竹"]
        actor["物品可用次数"] = {"爆竹": 1}
        result = be.execute_action(actor, {"类型": "物品", "物品": item,
                                           "目标": target["名称"]}, [actor, target])
        self.assertIn("无法被道具选中", result["错误"])
        self.assertEqual(actor["物品"], ["爆竹"])

        healer = make_char("丙", "敌方")
        healer["装备"] = {"武器1": SWORD}
        target["气血"] = 1000
        skill = be.load_skills().get("龙华剑术")
        with patch.object(be.random, "uniform", side_effect=[99, 1.0]):
            result = be.execute_action(healer, skill_action(skill, target), [healer, target])
        self.assertNotIn("错误", result)
        self.assertGreater(target["气血"], 1000)


if __name__ == "__main__":
    unittest.main()
