#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""即兴任务蓝图短期草稿存储。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common.json_io import JsonSchemaError, JsonSyntaxError  # noqa: E402
from store import quest_drafts  # noqa: E402


class QuestDraftStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save_dir = self.temp.name
        self.definition = {
            "quest_id": "draft-test",
            "version": 1,
            "name": "草稿测试",
            "intro": "",
            "hidden_goal": "",
            "start_nodes": ["start"],
            "nodes": {
                "start": {
                    "node_id": "start", "requires": [], "join": "all",
                    "condition": {}, "summary": "开始", "next": [],
                    "outcome": "closed", "visible": True, "extension": False,
                    "reward": None, "effects": [],
                },
            },
            "fact_definitions": [],
            "legacy": False,
        }

    def tearDown(self):
        self.temp.cleanup()

    def _record(self, quest_id="draft-test"):
        digest = quest_drafts.definition_hash("create", self.definition, False)
        return {
            "kind": "create",
            "payload": {"任务ID": quest_id},
            "hidden": False,
            "content_hash": digest,
            "quest_id": quest_id,
            "definition_version": 1,
            "summary": {"名称": "草稿测试"},
        }

    def test_hash_is_stable_across_mapping_order(self):
        reordered = dict(reversed(list(self.definition.items())))
        self.assertEqual(
            quest_drafts.definition_hash("create", self.definition, False),
            quest_drafts.definition_hash("create", reordered, False),
        )
        self.assertNotEqual(
            quest_drafts.definition_hash("create", self.definition, False),
            quest_drafts.definition_hash("create", self.definition, True),
        )

    def test_write_read_select_replace_and_clear_round(self):
        first = self._record()
        second = self._record("second")
        second["content_hash"] = "a" * 64
        batch = quest_drafts.write_batch(1, 3, [first, second], self.save_dir)
        self.assertEqual(batch["order"], ["draft-test", "second"])
        loaded = quest_drafts.read_drafts(1, self.save_dir)
        self.assertEqual(loaded["round"], 3)
        self.assertEqual(set(loaded["drafts"]), {"draft-test", "second"})
        selected = quest_drafts.select_drafts(
            1, ["second", "draft-test"], self.save_dir
        )
        self.assertEqual(
            [record["quest_id"] for record in selected["records"]],
            ["draft-test", "second"],
        )
        self.assertIn(os.path.join("slot_1", ".runtime", "quest_drafts.json"),
                      quest_drafts.quest_drafts_path(1, self.save_dir))

        replacement = self._record("replacement")
        replacement["content_hash"] = "b" * 64
        quest_drafts.write_batch(1, 3, [replacement], self.save_dir)
        self.assertEqual(
            quest_drafts.read_drafts(1, self.save_dir)["order"], ["replacement"]
        )

        quest_drafts.clear_round(1, 2, self.save_dir)
        self.assertTrue(os.path.exists(quest_drafts.quest_drafts_path(1, self.save_dir)))
        quest_drafts.clear_round(1, 3, self.save_dir)
        self.assertFalse(os.path.exists(quest_drafts.quest_drafts_path(1, self.save_dir)))

    def test_invalid_replacement_preserves_previous_batch(self):
        first = self._record()
        quest_drafts.write_batch(1, 3, [first], self.save_dir)
        invalid = self._record("invalid")
        invalid["content_hash"] = "bad"
        with self.assertRaises(JsonSchemaError):
            quest_drafts.write_batch(1, 3, [invalid], self.save_dir)
        self.assertEqual(quest_drafts.read_drafts(1, self.save_dir)["order"], ["draft-test"])

    def test_duplicate_or_missing_selection_is_rejected(self):
        quest_drafts.write_batch(1, 3, [self._record()], self.save_dir)
        with self.assertRaises(ValueError):
            quest_drafts.select_drafts(1, ["draft-test", "draft-test"], self.save_dir)
        with self.assertRaises(ValueError):
            quest_drafts.select_drafts(1, ["missing"], self.save_dir)

    def test_missing_file_is_empty_but_corruption_is_rejected(self):
        self.assertEqual(quest_drafts.read_drafts(2, self.save_dir)["drafts"], {})
        path = quest_drafts.quest_drafts_path(2, self.save_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write("{")
        with self.assertRaises(JsonSyntaxError):
            quest_drafts.read_drafts(2, self.save_dir)

        with open(path, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "drafts": {"bad": {}}}, file)
        with self.assertRaises(JsonSchemaError):
            quest_drafts.read_drafts(2, self.save_dir)


if __name__ == "__main__":
    unittest.main()
