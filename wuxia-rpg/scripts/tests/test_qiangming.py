#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【强命】状态结算回归测试。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import battle
from combat import battle_engine as be


def make_char(name="测试者", hp=10, mp=10):
    return {
        "名称": name,
        "阵营": "我方",
        "气血": hp,
        "内力": mp,
        "状态效果": [],
        "二级属性": {"气血上限": hp, "内力上限": mp},
    }


def qiangming_stacks(char):
    return sum(1 for e in char.get("状态效果", []) if e.get("id") == "qiangming")


class QiangmingTest(unittest.TestCase):
    def test_nonlethal_damage_does_not_consume(self):
        char = make_char()
        be.apply_status(char, "qiangming", 3)
        event = {"事件": "伤害", "攻击方": None, "目标": char,
                 "落气血": 5, "落内力": 0, "来源": "测试"}
        be.settle([char], event)
        self.assertEqual(char["气血"], 5)
        self.assertEqual(qiangming_stacks(char), 1)
        self.assertNotIn("强命保命", event)

    def test_each_lethal_event_consumes_one_stack(self):
        char = make_char()
        be.apply_status(char, "qiangming", 3)
        be.apply_status(char, "qiangming", 3)

        event = {"事件": "伤害", "攻击方": object(), "目标": char,
                 "落气血": 10, "落内力": 0, "来源": "测试"}
        be.settle([char], event)
        self.assertEqual(char["气血"], 1)
        self.assertEqual(qiangming_stacks(char), 1)
        self.assertEqual(event["强命保命"]["名称"], "强命")

        char["气血"] = 10
        event2 = {"事件": "伤害", "攻击方": object(), "目标": char,
                  "落气血": 99, "落内力": 0, "来源": "测试"}
        be.settle([char], event2)
        self.assertEqual(char["气血"], 1)
        self.assertEqual(qiangming_stacks(char), 0)

    def test_without_stack_lethal_damage_reaches_zero(self):
        char = make_char()
        event = {"事件": "伤害", "攻击方": None, "目标": char,
                 "落气血": 10, "落内力": 0, "来源": "测试"}
        be.settle([char], event)
        self.assertEqual(char["气血"], 0)

    def test_dot_can_trigger_qiangming(self):
        char = make_char(hp=5)
        be.apply_status(char, "qiangming", 3)
        result = {}
        be.apply_dot_events(char, [{"类型": "持续伤害", "数值": 5,
                                    "来源": "测试", "目标": char["名称"]}], result, [char])
        self.assertEqual(char["气血"], 1)
        self.assertEqual(result["持续伤害"][0]["数值"], 4)
        self.assertNotIn("持续伤害击败", result)
        self.assertEqual(result["强命保命"][0]["名称"], "强命")

    def test_hp_cost_can_trigger_qiangming(self):
        char = make_char(hp=5)
        be.apply_status(char, "qiangming", 3)
        event = {"事件": "消耗", "行动者": char,
                 "扣气血": 5, "扣内力": 0, "来源": "测试"}
        be.settle([char], event)
        self.assertEqual(char["气血"], 1)
        self.assertEqual(qiangming_stacks(char), 0)
        self.assertIn("强命保命", event)

    def test_zero_final_hp_loss_does_not_consume(self):
        char = make_char(hp=5)
        be.apply_status(char, "qiangming", 3)
        event = {"事件": "伤害", "攻击方": None, "目标": char,
                 "落气血": 0, "落内力": 5, "来源": "测试"}
        be.settle([char], event)
        self.assertEqual(char["气血"], 5)
        self.assertEqual(qiangming_stacks(char), 1)

    def test_report_clause(self):
        text = battle.qiangming_clause_of({"强命保命": [{"目标": "甲", "名称": "强命"}]})
        self.assertEqual(text, "甲由【强命】护住最后1点气血")


if __name__ == "__main__":
    unittest.main()
