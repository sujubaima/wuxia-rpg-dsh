#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态管理、状态快照与七星逆脉结算回归。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import battle_engine as be
from common import status_manager as sm


def make_char(name="甲", team="我方", hp=100, mp=100):
    attrs = {
        "气血上限": 100, "内力上限": 100,
        "攻击力": 100, "防御力": 100, "精准": 100, "识破": 100,
        "暴击": 100, "速度": 100,
        "力道": 10, "根骨": 10, "内功": 10, "身法": 10,
        "休息气血恢复": 0, "休息内力恢复": 0.1,
    }
    return {
        "名称": name, "阵营": team, "气血": hp, "内力": mp,
        "状态效果": [], "二级属性": attrs,
        "一级属性": {"力道": 10, "根骨": 10, "内功": 10, "身法": 10},
        "武艺": {"剑法": 10, "刀法": 10, "长兵": 10,
                 "奇门": 10, "暗器": 10, "搏击": 10},
        "武学": [], "冷却": {}, "充能": 0, "装备": {}, "物品": [],
    }


def action_source(actor, module):
    skill = {"名称": "测试武学", "类型": "剑法"}
    return skill, {"类型": "技能特效", "持有者": actor, "数据": skill,
                   "模块": module, "id": "probe", "名称": "测试武学"}


class StatusManagerTest(unittest.TestCase):
    def test_stacking_modes_and_extra_refresh(self):
        char = make_char()
        sm.apply_status(char, "fengji", 2, extra={"封禁品级": [2]})
        sm.apply_status(char, "fengji", 5, extra={"封禁品级": [2, 3]})
        entries = [e for e in char["状态效果"] if e["id"] == "fengji"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["剩余时间"], 2)
        self.assertEqual(entries[0]["封禁品级"], [2, 3])

        sm.apply_status(char, "counter_attack", 2)
        sm.apply_status(char, "counter_attack", 5)
        counter = next(e for e in char["状态效果"] if e["id"] == "counter_attack")
        self.assertEqual(counter["剩余时间"], 5)
        sm.apply_status(char, "counter_attack", -1)
        self.assertEqual(counter["剩余时间"], -1)

        sm.apply_status(char, "qiangming", 2)
        sm.apply_status(char, "qiangming", 2)
        self.assertEqual(sum(e["id"] == "qiangming" for e in char["状态效果"]), 2)

    def test_self_duration_compensation_excludes_turn_end_statuses(self):
        char = make_char()
        sm.apply_status(char, "iron_wall", 2, actor=char)
        sm.apply_status(char, "huichun", 2, actor=char)
        iron = next(e for e in char["状态效果"] if e["id"] == "iron_wall")
        heal = next(e for e in char["状态效果"] if e["id"] == "huichun")
        self.assertEqual(iron["剩余时间"], 3)
        self.assertEqual(heal["剩余时间"], 2)

        other = make_char("乙")
        sm.apply_status(other, "iron_wall", 2, actor=char)
        self.assertEqual(other["状态效果"][0]["剩余时间"], 2)

    def test_remove_calls_on_removed_only_after_last_layer(self):
        char = make_char()
        first = {"id": "probe", "剩余时间": 2}
        second = {"id": "probe", "剩余时间": 2}
        char["状态效果"] = [first, second]
        removed = Mock()
        module = SimpleNamespace(on_removed=removed)
        with patch.object(sm.el, "load_effect", return_value=module):
            self.assertTrue(sm.remove_status(char, first))
            removed.assert_not_called()
            self.assertTrue(sm.remove_status(char, second))
        removed.assert_called_once_with(char)
        self.assertFalse(sm.remove_status(char, second))

    def test_tick_and_clear_preserve_world_statuses(self):
        char = make_char()
        battle_entry = {"id": "iron_wall", "剩余时间": 1, "场景": "战斗"}
        world_entry = {"id": "swift", "剩余时间": 5, "场景": "大世界"}
        permanent = {"id": "qiangming", "剩余时间": -1, "场景": "战斗"}
        char["状态效果"] = [battle_entry, world_entry, permanent]
        expired = sm.tick_cooldowns_and_buffs(char)
        self.assertEqual([e["id"] for e in expired], ["iron_wall"])
        self.assertIn(world_entry, char["状态效果"])
        self.assertIn(permanent, char["状态效果"])
        sm.clear_active_statuses([char])
        self.assertEqual(char["状态效果"], [world_entry])

    def test_wugu_removed_cleans_private_lifecycle_state(self):
        char = make_char()
        sm.apply_status(char, "wugu", 3, extra={"削减比例": 0.1})
        self.assertEqual(char["_巫蛊基数"], 100)
        self.assertEqual(char["_巫蛊回合"], 0)
        entry = next(e for e in char["状态效果"] if e["id"] == "wugu")
        sm.remove_status(char, entry)
        self.assertNotIn("_巫蛊基数", char)
        self.assertNotIn("_巫蛊回合", char)


class StatusSnapshotTest(unittest.TestCase):
    def test_action_removal_skips_snapshotted_status(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        entry = {"id": "victim", "剩余时间": 2}
        target["状态效果"] = [entry]
        calls = []

        def remove(source, ctx):
            sm.remove_status(target, entry)

        skill, source = action_source(actor, SimpleNamespace(on_action=remove))
        status_mod = SimpleNamespace(on_action=lambda source, ctx: calls.append("不应执行"))
        ctx = be.make_combat_context(actor, skill, {}, [actor, target], action_source=source)
        with patch.object(be.el, "load_effect", return_value=status_mod):
            be.dispatch_combat_stage("on_action", ctx, source)
        self.assertEqual(calls, [])

    def test_partial_stack_removal_refreshes_layer_count(self):
        actor = make_char()
        entries = [{"id": "stack", "剩余时间": 2} for _ in range(3)]
        actor["状态效果"] = entries[:]
        seen = []

        def remove_one(source, ctx):
            sm.remove_status(actor, entries[0])

        skill, source = action_source(actor, SimpleNamespace(on_action=remove_one))
        status_mod = SimpleNamespace(
            on_action=lambda source, ctx: seen.append((source["层数"], len(source["条目"]))))
        ctx = be.make_combat_context(actor, skill, {}, [actor], action_source=source)
        with patch.object(be.el, "load_effect", return_value=status_mod):
            be.dispatch_combat_stage("on_action", ctx, source)
        self.assertEqual(seen, [(2, 2)])

    def test_owner_leaving_fight_skips_snapshotted_status(self):
        actor = make_char()
        target = make_char("乙", "敌方")
        target["状态效果"] = [{"id": "state", "剩余时间": 2}]
        calls = []

        def defeat(source, ctx):
            target["气血"] = 0

        skill, source = action_source(actor, SimpleNamespace(on_action=defeat))
        status_mod = SimpleNamespace(on_action=lambda source, ctx: calls.append("不应执行"))
        ctx = be.make_combat_context(actor, skill, {}, [actor, target], action_source=source)
        with patch.object(be.el, "load_effect", return_value=status_mod):
            be.dispatch_combat_stage("on_action", ctx, source)
        self.assertEqual(calls, [])


class QixingSettlementTest(unittest.TestCase):
    def setUp(self):
        self.char = make_char(hp=50, mp=50)
        sm.apply_status(self.char, "qixing_nimai", -1)
        self.module = be.el.load_effect("qixing_nimai")

    def test_damage_routes_to_mp_on_trigger(self):
        event = {"事件": "伤害", "攻击方": object(), "目标": self.char,
                 "落气血": 80, "落内力": 0, "来源": "测试"}
        with patch.object(self.module.random, "random", return_value=0):
            be.settle([self.char], event)
        self.assertEqual(self.char["气血"], 50)
        self.assertEqual(self.char["内力"], 0)
        self.assertEqual(event["落气血"], 0)
        self.assertEqual(event["落内力"], 50)

    def test_damage_stays_on_hp_when_not_triggered(self):
        event = {"事件": "伤害", "攻击方": object(), "目标": self.char,
                 "落气血": 20, "落内力": 0, "来源": "测试"}
        with patch.object(self.module.random, "random", return_value=1):
            be.settle([self.char], event)
        self.assertEqual(self.char["气血"], 30)
        self.assertEqual(self.char["内力"], 50)

    def test_heal_routes_to_mp_with_capacity_limit(self):
        self.char["气血"] = 20
        self.char["内力"] = 80
        event = {"事件": "治疗", "攻击方": None, "目标": self.char,
                 "落气血": 50, "落内力": 0, "来源": "测试"}
        with patch.object(self.module.random, "random", return_value=0):
            be.settle([self.char], event)
        self.assertEqual(self.char["气血"], 50)
        self.assertEqual(self.char["内力"], 100)
        self.assertEqual(event["落气血"], 30)
        self.assertEqual(event["落内力"], 20)

    def test_mp_recovery_routes_to_hp_with_capacity_limit(self):
        self.char["气血"] = 80
        self.char["内力"] = 20
        event = {"事件": "内力恢复", "攻击方": None, "目标": self.char,
                 "落气血": 0, "落内力": 50, "来源": "测试"}
        with patch.object(self.module.random, "random", return_value=0):
            be.settle([self.char], event)
        self.assertEqual(self.char["气血"], 100)
        self.assertEqual(self.char["内力"], 50)
        self.assertEqual(event["落气血"], 20)
        self.assertEqual(event["落内力"], 30)

    def test_cost_preview_never_rolls_or_rewrites(self):
        random_mock = Mock(return_value=0)
        with patch.object(self.module.random, "random", random_mock):
            reason = be.cost_blocked_reason(self.char, 60, [self.char], "测试")
        self.assertEqual(reason, "内力不足")
        random_mock.assert_not_called()
        self.assertEqual((self.char["气血"], self.char["内力"]), (50, 50))

    def test_real_cost_can_route_to_hp(self):
        self.char["气血"] = 80
        event = {"事件": "消耗", "行动者": self.char,
                 "扣气血": 0, "扣内力": 30, "来源": "测试"}
        with patch.object(self.module.random, "random", return_value=0):
            be.settle([self.char], event)
        self.assertEqual(self.char["气血"], 50)
        self.assertEqual(self.char["内力"], 50)
        self.assertEqual(event["扣气血"], 30)
        self.assertEqual(event["扣内力"], 0)

    def test_mastery_changes_trigger_probability(self):
        self.assertEqual(self.module.trigger_prob(self.char), 0.40)
        self.char["武学"] = [{"名称": "七星逆脉", "等级": 10}]
        self.assertEqual(self.module.trigger_prob(self.char), 0.60)


if __name__ == "__main__":
    unittest.main()
