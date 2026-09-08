#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物品效果、使用限制和状态回合生命周期回归。"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import battle_engine as be
from common import status_manager as sm


def make_char(name="甲", team="我方", hp=1000, mp=1000):
    attrs = {
        "气血上限": 1000, "内力上限": 1000,
        "攻击力": 150, "防御力": 120, "精准": 120, "识破": 120,
        "暴击": 80, "速度": 100,
        "力道": 30, "根骨": 30, "内功": 30, "身法": 30,
        "休息气血恢复": 0, "休息内力恢复": 0.1,
    }
    return {
        "名称": name, "阵营": team, "气血": hp, "内力": mp,
        "气血上限": 1000, "内力上限": 1000,
        "状态效果": [], "二级属性": attrs,
        "一级属性": {"力道": 30, "根骨": 30, "内功": 30, "身法": 30},
        "武艺": {"剑法": 10, "刀法": 10, "长兵": 10,
                 "奇门": 10, "暗器": 10, "搏击": 10},
        "武学": [], "冷却": {}, "充能": 0, "装备": {}, "物品": [],
    }


def use_item(actor, target, name, characters=None, count=1):
    item = be.load_items()[name]
    actor["物品"] = [name] * count
    actor["物品可用次数"] = {name: min(count, 2)}
    return be.execute_action(actor, {"类型": "物品", "物品": item,
                                     "目标": target["名称"]},
                             characters or [actor, target])


def deterministic_roll(a, b):
    return 1.0 if b <= 1.05 else 99


class ItemEffectTest(unittest.TestCase):
    def test_mp_recovery_clamps_and_consumes_inventory_and_limit(self):
        actor = make_char()
        target = make_char("乙", mp=800)
        result = use_item(actor, target, "补气丸")
        self.assertEqual(result["恢复内力"], 200)
        self.assertEqual(result["目标内力变化"], {"原值": 800, "新值": 1000})
        self.assertEqual(actor["物品"], [])
        self.assertEqual(actor["物品可用次数"]["补气丸"], 0)

    def test_status_item_applies_declared_layers_and_duration(self):
        actor = make_char(hp=500)
        result = use_item(actor, actor, "回春散", [actor])
        entries = [e for e in actor["状态效果"] if e["id"] == "huichun"]
        self.assertEqual(len(entries), 2)
        self.assertEqual([e["剩余时间"] for e in entries], [3, 3])
        self.assertEqual(len(result["施加状态"]), 2)
        self.assertTrue(all(row["持续时间"] == 3 for row in result["施加状态"]))

    def test_sequence_item_changes_charge(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        target["充能"] = 50
        result = use_item(actor, target, "爆竹")
        self.assertEqual(target["充能"], -50)
        self.assertEqual(result["时序变化"], [
            {"目标": "乙", "变化": -100, "原值": 50, "新值": -50}
        ])

    def test_purify_removes_one_eligible_negative_only(self):
        actor = make_char()
        target = make_char("乙")
        sm.apply_status(target, "dazzle", 2)
        sm.apply_status(target, "po_fang", 2)
        sm.apply_status(target, "iron_wall", 2)
        sm.apply_status(target, "sangong", -1)
        sm.apply_status(target, "dazzle", 5, scene="大世界")
        picked = next(e for e in target["状态效果"]
                      if e["id"] == "po_fang" and e["场景"] == "战斗")
        with patch.object(be.random, "choice", return_value=picked):
            result = use_item(actor, target, "清心露")
        self.assertEqual([row["id"] for row in result["净化状态"]], ["po_fang"])
        remaining = [(e["id"], e["场景"]) for e in target["状态效果"]]
        self.assertNotIn(("po_fang", "战斗"), remaining)
        self.assertIn(("dazzle", "战斗"), remaining)
        self.assertIn(("iron_wall", "战斗"), remaining)
        self.assertIn(("sangong", "战斗"), remaining)
        self.assertIn(("dazzle", "大世界"), remaining)

    def test_weaken_reduces_all_finite_battle_debuffs_and_expires_zero(self):
        actor = make_char()
        target = make_char("乙")
        sm.apply_status(target, "dazzle", 1)
        sm.apply_status(target, "po_fang", 3)
        sm.apply_status(target, "iron_wall", 2)
        sm.apply_status(target, "sangong", -1)
        sm.apply_status(target, "dazzle", 5, scene="大世界")
        result = use_item(actor, target, "保和丸")
        rows = {row["id"]: row for row in result["削减状态"]}
        self.assertEqual(rows["dazzle"]["新剩余"], 0)
        self.assertTrue(rows["dazzle"]["失效"])
        self.assertEqual(rows["po_fang"]["新剩余"], 2)
        self.assertFalse(rows["po_fang"]["失效"])
        self.assertEqual(next(e for e in target["状态效果"] if e["id"] == "iron_wall")["剩余时间"], 2)
        self.assertEqual(next(e for e in target["状态效果"] if e["id"] == "sangong")["剩余时间"], -1)
        world = next(e for e in target["状态效果"] if e["场景"] == "大世界")
        self.assertEqual(world["剩余时间"], 5)

    def test_extend_affects_only_finite_battle_buffs(self):
        actor = make_char()
        target = make_char("乙")
        sm.apply_status(target, "iron_wall", 2)
        sm.apply_status(target, "huichun", 3)
        sm.apply_status(target, "dazzle", 2)
        sm.apply_status(target, "ren_jian_he_yi", -1)
        sm.apply_status(target, "iron_wall", 5, scene="大世界")
        result = use_item(actor, target, "百花丸")
        rows = {row["id"]: row for row in result["延长状态"]}
        self.assertEqual(rows["iron_wall"]["新剩余"], 3)
        self.assertEqual(rows["huichun"]["新剩余"], 4)
        negative = next(e for e in target["状态效果"] if e["id"] == "dazzle")
        permanent = next(e for e in target["状态效果"] if e["id"] == "ren_jian_he_yi")
        world = next(e for e in target["状态效果"] if e["场景"] == "大世界")
        self.assertEqual(negative["剩余时间"], 2)
        self.assertEqual(permanent["剩余时间"], -1)
        self.assertEqual(world["剩余时间"], 5)

    def test_invalid_target_and_exhausted_limit_do_not_consume_item(self):
        actor = make_char()
        item = be.load_items()["小还丹"]
        actor["物品"] = ["小还丹"]
        actor["物品可用次数"] = {"小还丹": 1}
        result = be.execute_action(actor, {"类型": "物品", "物品": item,
                                           "目标": "不存在"}, [actor])
        self.assertEqual(result["错误"], "目标无效或已败阵")
        self.assertEqual(actor["物品"], ["小还丹"])
        self.assertEqual(actor["物品可用次数"]["小还丹"], 1)

        actor["物品可用次数"]["小还丹"] = 0
        result = be.execute_action(actor, {"类型": "物品", "物品": item,
                                           "目标": actor["名称"]}, [actor])
        self.assertIn("本场可用次数已用尽", result["错误"])
        self.assertEqual(actor["物品"], ["小还丹"])


class TurnLifecycleTest(unittest.TestCase):
    def battle_state(self, actor, enemy):
        return {"角色列表": [actor, enemy], "回合数": 0, "当前行动者": actor["名称"]}

    def test_fenshen_accumulates_turn_damage_and_recoils_at_turn_end(self):
        actor = make_char(hp=1000)
        enemy = make_char("乙", "敌方")
        sm.apply_status(actor, "fenshen", -1, extra={"武学等级": 10})
        skill = be.load_skills().get("太祖长拳")
        action = {"类型": "武学", "技能": skill, "目标": enemy["名称"]}
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            turn = be.process_turn(self.battle_state(actor, enemy), action)
        result = turn["结算"]
        dealt = result["伤害"]
        recoil = result["持续伤害"][0]
        self.assertEqual(recoil["来源"], "焚身")
        self.assertEqual(recoil["数值"], dealt)
        self.assertEqual(actor["气血"], 1000 - dealt)
        self.assertEqual(actor["_焚身蓄"], 0)

    def test_wugu_reduces_cap_linearly_then_expiry_restores_cap_not_hp(self):
        actor = make_char()
        enemy = make_char("乙", "敌方")
        sm.apply_status(actor, "wugu", 3, extra={"削减比例": 0.1})
        state = self.battle_state(actor, enemy)
        for expected_cap, expected_hp, remaining in ((900, 900, 2), (800, 800, 1)):
            turn = be.process_turn(state, {"类型": "休息"})
            self.assertEqual(be.status_attr(actor, "气血上限"), expected_cap)
            self.assertEqual(actor["气血"], expected_hp)
            self.assertEqual(actor["状态效果"][0]["剩余时间"], remaining)
            state = turn["战场状态"]
            state["当前行动者"] = actor["名称"]
        turn = be.process_turn(state, {"类型": "休息"})
        self.assertEqual(be.status_attr(actor, "气血上限"), 1000)
        self.assertEqual(actor["气血"], 700)
        self.assertNotIn("_巫蛊基数", actor)
        self.assertNotIn("_巫蛊回合", actor)
        self.assertEqual(turn["结算"]["状态失效"], [{"id": "wugu", "名称": "巫蛊"}])

    def test_hot_dot_layers_trigger_each_turn_and_expire_after_last_tick(self):
        actor = make_char(hp=500)
        enemy = make_char("乙", "敌方")
        sm.apply_status(actor, "huichun", 2)
        sm.apply_status(actor, "huichun", 2)
        sm.apply_status(actor, "wai_shang", 2)
        state = self.battle_state(actor, enemy)

        first = be.process_turn(state, {"类型": "休息"})
        result = first["结算"]
        self.assertEqual(len(result["持续恢复"]), 2)
        self.assertEqual(len(result["持续伤害"]), 1)
        self.assertEqual(actor["气血"], 550)
        self.assertEqual([e["剩余时间"] for e in actor["状态效果"]], [1, 1, 1])

        state = first["战场状态"]
        state["当前行动者"] = actor["名称"]
        second = be.process_turn(state, {"类型": "休息"})
        result = second["结算"]
        self.assertEqual(len(result["持续恢复"]), 2)
        self.assertEqual(len(result["持续伤害"]), 1)
        self.assertEqual(actor["气血"], 600)
        self.assertEqual(actor["状态效果"], [])
        self.assertEqual({row["id"] for row in result["状态失效"]}, {"huichun", "wai_shang"})


if __name__ == "__main__":
    unittest.main()
