#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务条件三值求值与事实定义类型校验。"""
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from quest.conditions import condition_possible, evaluate_condition  # noqa: E402
from quest.engine import create_quest  # noqa: E402
from quest.models import empty_quest_state  # noqa: E402
from quest.world_facts import (empty_world_facts, register_definition,  # noqa: E402
                               upsert_fact)


AUTHENTICITY = "item:condition-ledger.authenticity@world"
DISCOVERED = "information:condition-case:trace.discovered@world"
HP = "character:condition-witness.hp@world"
TERMS = "information:condition-case:agreement.terms@world"


def _facts():
    facts = empty_world_facts()
    definitions = [
        {"事实键": AUTHENTICITY, "值类型": "enum",
         "可选值": ["authentic", "forged"]},
        {"事实键": DISCOVERED, "值类型": "bool"},
        {"事实键": HP, "值类型": "number"},
        {"事实键": TERMS, "值类型": "set"},
    ]
    for definition in definitions:
        register_definition(facts, definition)
    return facts


def _blueprint(condition, fact_definitions=None, name="条件校验"):
    return {
        "版本": 1,
        "名称": name,
        "事实定义": list(fact_definitions or []),
        "起始节点": ["done"],
        "节点": [{
            "节点ID": "done", "完成条件": condition,
            "关闭条件": None, "关闭描述": None,
            "完成摘要": "完成。", "终局": True,
        }],
    }


class ThreeValuedConditionTest(unittest.TestCase):
    def test_missing_and_alleged_values_remain_unknown_under_not(self):
        facts = _facts()
        positive = {"fact": DISCOVERED, "eq": True}
        negative = {"not": positive}
        self.assertFalse(evaluate_condition(positive, facts))
        self.assertFalse(evaluate_condition(negative, facts))
        self.assertFalse(evaluate_condition({
            "not": {"fact": DISCOVERED, "status": "verified"},
        }, facts))
        self.assertTrue(condition_possible(positive, facts))
        self.assertTrue(condition_possible(negative, facts))

        upsert_fact(facts, DISCOVERED, True, status="alleged")
        self.assertFalse(evaluate_condition(positive, facts))
        self.assertFalse(evaluate_condition(negative, facts))

    def test_verified_value_makes_positive_or_negative_decidable(self):
        facts = _facts()
        upsert_fact(facts, DISCOVERED, False)
        positive = {"fact": DISCOVERED, "eq": True}
        self.assertFalse(evaluate_condition(positive, facts))
        self.assertTrue(evaluate_condition({"not": positive}, facts))

    def test_all_and_any_propagate_unknown(self):
        facts = _facts()
        upsert_fact(facts, AUTHENTICITY, "authentic")
        known = {"fact": AUTHENTICITY, "eq": "authentic"}
        unknown = {"fact": DISCOVERED, "eq": True}
        false = {"fact": AUTHENTICITY, "eq": "forged"}
        self.assertFalse(evaluate_condition({"all": [known, unknown]}, facts))
        self.assertTrue(evaluate_condition({"any": [known, unknown]}, facts))
        self.assertFalse(evaluate_condition({"any": [false, unknown]}, facts))
        self.assertFalse(evaluate_condition({"not": {"any": [false, unknown]}}, facts))

    def test_status_and_exists_are_explicit_observations(self):
        facts = _facts()
        self.assertFalse(evaluate_condition({"fact": DISCOVERED, "exists": True}, facts))
        upsert_fact(facts, DISCOVERED, True, status="alleged")
        self.assertTrue(evaluate_condition({"fact": DISCOVERED, "exists": True}, facts))
        self.assertTrue(evaluate_condition({"fact": DISCOVERED, "status": "alleged"}, facts))
        self.assertFalse(evaluate_condition({"fact": DISCOVERED, "eq": True}, facts))


class TypedConditionValidationTest(unittest.TestCase):
    def _reject(self, condition, message):
        with self.assertRaisesRegex(ValueError, message):
            create_quest(_facts(), empty_quest_state(), _blueprint(condition))

    def test_accepts_matching_comparators(self):
        cases = [
            {"fact": AUTHENTICITY, "eq": "authentic"},
            {"fact": AUTHENTICITY, "in": ["authentic", "forged"]},
            {"fact": HP, "gte": 1},
            {"fact": TERMS, "eq": ["safe-passage", "payment"]},
            {"fact": DISCOVERED, "exists": True},
            {"fact": DISCOVERED, "status": "verified"},
        ]
        for index, condition in enumerate(cases):
            with self.subTest(condition=condition):
                create_quest(_facts(), empty_quest_state(),
                             _blueprint(condition, name=f"条件校验{index}"))

    def test_rejects_comparator_type_mismatches(self):
        cases = [
            ({"fact": AUTHENTICITY, "eq": "missing"}, "取值不符合 enum"),
            ({"fact": AUTHENTICITY, "gt": "authentic"}, "仅支持 number"),
            ({"fact": HP, "gte": True}, "取值不符合 number"),
            ({"fact": TERMS, "in": ["payment"]}, "set 事实不支持 in"),
            ({"fact": AUTHENTICITY, "in": []}, "非空数组"),
            ({"fact": DISCOVERED, "exists": False}, "禁止 exists:false"),
            ({"not": {"fact": DISCOVERED, "exists": True}}, "等价否定"),
        ]
        for condition, message in cases:
            with self.subTest(condition=condition):
                self._reject(condition, message)

    def test_rejects_own_outcome_as_completion_condition(self):
        outcome = "quest:condition-case.outcome@world"
        definition = {"事实键": outcome, "描述": "任务结果", "值类型": "enum",
                      "可选值": ["solved", "abandoned"]}
        with self.assertRaisesRegex(ValueError, "自身 outcome"):
            create_quest(empty_world_facts(), empty_quest_state(),
                         _blueprint({"fact": outcome, "eq": "solved"}, [definition]))

    def test_invalid_creation_does_not_register_definition(self):
        facts = empty_world_facts()
        new_fact = "information:atomic-case:trace.discovered@world"
        definition = {"事实键": new_fact, "描述": "具体踪迹已经找到", "值类型": "bool"}
        with self.assertRaisesRegex(ValueError, "禁止 exists:false"):
            create_quest(facts, empty_quest_state(),
                         _blueprint({"fact": new_fact, "exists": False}, [definition]))
        self.assertNotIn(new_fact, facts["definitions"])


if __name__ == "__main__":
    unittest.main()
