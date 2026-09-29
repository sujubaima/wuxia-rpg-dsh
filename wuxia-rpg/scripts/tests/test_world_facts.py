#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局事实表的类型、认知边界、互斥与修订规则。"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from quest.world_facts import (empty_world_facts, normalize_world_facts,
                                register_definition, upsert_fact)


class WorldFactsTest(unittest.TestCase):
    def setUp(self):
        self.store = empty_world_facts()
        register_definition(self.store, {
            "事实键": "item:ledger_001.authenticity@world",
            "值类型": "enum", "可选值": ["authentic", "forged"],
        })

    def test_same_fact_is_idempotent_and_conflicting_verified_requires_revision(self):
        changed, _, _ = upsert_fact(
            self.store, "item:ledger_001.authenticity@world", "forged"
        )
        self.assertTrue(changed)
        changed, _, _ = upsert_fact(
            self.store, "item:ledger_001.authenticity@world", "forged"
        )
        self.assertFalse(changed)
        with self.assertRaisesRegex(ValueError, "显式事实修订"):
            upsert_fact(self.store, "item:ledger_001.authenticity@world", "authentic")
        changed, before, after = upsert_fact(
            self.store, "item:ledger_001.authenticity@world", "authentic",
            revision=True, reason="发现此前鉴定对象已被调包",
        )
        self.assertTrue(changed)
        self.assertEqual(before["value"], "forged")
        self.assertEqual(after["value"], "authentic")

    def test_objective_fact_and_character_claim_can_disagree(self):
        register_definition(self.store, {
            "事实键": "item:ledger_001.authenticity@character:掌柜",
            "值类型": "enum", "可选值": ["authentic", "forged"],
        })
        upsert_fact(self.store, "item:ledger_001.authenticity@world", "forged")
        upsert_fact(
            self.store, "item:ledger_001.authenticity@character:掌柜",
            "authentic", status="alleged",
        )
        self.assertEqual(len(self.store["records"]), 2)

    def test_exclusive_group_rejects_two_active_truths(self):
        for key in ("choice:guild:a.selected@world", "choice:guild:b.selected@world"):
            register_definition(self.store, {
                "事实键": key, "值类型": "bool", "互斥组": "guild-controller",
            })
        upsert_fact(self.store, "choice:guild:a.selected@world", True)
        with self.assertRaisesRegex(ValueError, "互斥组"):
            upsert_fact(self.store, "choice:guild:b.selected@world", True)

    def test_set_values_are_order_independent(self):
        key = "information:ledger:source-list.terms@world"
        register_definition(self.store, {"事实键": key, "值类型": "set"})
        changed, _, after = upsert_fact(self.store, key, ["seal", "ink", "seal"])
        self.assertTrue(changed)
        self.assertEqual(after["value"], ["ink", "seal"])
        changed, _, _ = upsert_fact(self.store, key, ["seal", "ink"])
        self.assertFalse(changed)

    def test_definition_rejects_unknown_revision_policy(self):
        with self.assertRaisesRegex(ValueError, "修订策略"):
            register_definition(self.store, {
                "事实键": "player.region@world", "值类型": "string",
                "修订策略": "sometimes",
            })

    def test_enum_value_is_validated(self):
        with self.assertRaisesRegex(ValueError, "不符合"):
            upsert_fact(self.store, "item:ledger_001.authenticity@world", "unknown-kind")

    def test_description_enriches_legacy_definition_and_rejects_conflict(self):
        key = "item:ledger_001.authenticity@world"
        self.assertEqual(self.store["definitions"][key]["description"], "")
        changed = register_definition(self.store, {
            "事实键": key, "描述": "账册的真实真伪",
            "值类型": "enum", "可选值": ["authentic", "forged"],
        })
        self.assertTrue(changed)
        self.assertEqual(self.store["definitions"][key]["description"], "账册的真实真伪")
        with self.assertRaisesRegex(ValueError, "现有描述【账册的真实真伪】"):
            register_definition(self.store, {
                "事实键": key, "描述": "账册是真是假",
                "值类型": "enum", "可选值": ["authentic", "forged"],
            })

    def test_mechanical_dynamic_predicates_enforce_value_types(self):
        register_definition(self.store, {
            "事实键": "character:阿青.item:短剑:quantity@world", "值类型": "number",
        })
        register_definition(self.store, {
            "事实键": "character:阿青.skill:越女剑:known@world", "值类型": "bool",
        })
        with self.assertRaisesRegex(ValueError, "不支持值类型"):
            register_definition(self.store, {
                "事实键": "character:阿青.skill:越女剑:level@world", "值类型": "bool",
            })

    def test_rejects_unknown_predicate_wrong_family_and_abstract_tokens(self):
        cases = [
            {"事实键": "item:ledger.truth@world", "值类型": "bool"},
            {"事实键": "case:ledger.discovered@world", "值类型": "bool"},
            {"事实键": "character:掌柜.authenticity@world", "值类型": "enum",
             "可选值": ["authentic", "forged"]},
            {"事实键": "information:case:truth.discovered@world", "值类型": "bool"},
        ]
        for definition in cases:
            with self.subTest(definition=definition):
                with self.assertRaises(ValueError):
                    register_definition(self.store, definition)

    def test_explicit_parts_must_match_fact_key(self):
        with self.assertRaisesRegex(ValueError, "显式谓词"):
            register_definition(self.store, {
                "事实键": "item:ledger_002.authenticity@world",
                "谓词": "origin", "值类型": "enum",
                "可选值": ["authentic", "forged"],
            })
        with self.assertRaisesRegex(ValueError, "显式主体"):
            register_definition(self.store, {
                "事实键": "item:ledger_002.authenticity@world",
                "主体": "item:other", "值类型": "enum",
                "可选值": ["authentic", "forged"],
            })

    def test_normalize_store_revalidates_existing_definitions(self):
        invalid = {
            "version": 1,
            "definitions": {
                "case:ledger.truth@world": {
                    "fact_key": "case:ledger.truth@world", "subject": "case:ledger",
                    "predicate": "truth", "scope": "world", "value_type": "bool",
                },
            },
            "records": {},
        }
        with self.assertRaises(ValueError):
            normalize_world_facts(invalid)


if __name__ == "__main__":
    unittest.main()
