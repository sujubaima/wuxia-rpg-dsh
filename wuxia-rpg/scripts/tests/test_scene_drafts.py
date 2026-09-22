#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景规划短期草稿存储。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common.json_io import JsonSchemaError, JsonSyntaxError  # noqa: E402
from store import scene_drafts  # noqa: E402


class SceneDraftStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save_dir = self.temp.name
        self.operations = [{
            "类型": "登记场景", "区域": "苏州", "场景": "废园",
            "方位出口": {"东": "平江路"},
        }]

    def tearDown(self):
        self.temp.cleanup()

    def test_write_read_replace_and_clear(self):
        with patch("store.scene_drafts.sm._slot_writable", return_value=True):
            written = scene_drafts.write_batch(1, 3, self.operations, self.save_dir)
            self.assertEqual(written["operations"], self.operations)
            self.assertEqual(scene_drafts.read_draft(1, self.save_dir)["round"], 3)

            replacement = [{"类型": "隔离地点", "区域": "苏州", "场景": "废园"}]
            scene_drafts.write_batch(1, 3, replacement, self.save_dir)
            self.assertEqual(
                scene_drafts.select_draft(1, self.save_dir)["operations"], replacement
            )

            scene_drafts.clear_round(1, 2, self.save_dir)
            self.assertTrue(os.path.exists(scene_drafts.scene_drafts_path(1, self.save_dir)))
            scene_drafts.clear_round(1, 3, self.save_dir)
            self.assertFalse(os.path.exists(scene_drafts.scene_drafts_path(1, self.save_dir)))

    def test_empty_batch_clears_draft(self):
        with patch("store.scene_drafts.sm._slot_writable", return_value=True):
            scene_drafts.write_batch(1, 3, self.operations, self.save_dir)
            result = scene_drafts.write_batch(1, 3, [], self.save_dir)
        self.assertEqual(result["operations"], [])
        self.assertFalse(os.path.exists(scene_drafts.scene_drafts_path(1, self.save_dir)))

    def test_corruption_and_hash_mismatch_are_rejected(self):
        path = scene_drafts.scene_drafts_path(1, self.save_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write("{")
        with self.assertRaises(JsonSyntaxError):
            scene_drafts.read_draft(1, self.save_dir)

        with open(path, "w", encoding="utf-8") as file:
            json.dump({
                "version": 1, "slot": 1, "round": 3,
                "operations": self.operations, "content_hash": "0" * 64,
            }, file, ensure_ascii=False)
        with self.assertRaises(JsonSchemaError):
            scene_drafts.read_draft(1, self.save_dir)

    def test_invalid_operation_is_rejected_without_replacing(self):
        with patch("store.scene_drafts.sm._slot_writable", return_value=True):
            scene_drafts.write_batch(1, 3, self.operations, self.save_dir)
            with self.assertRaises(JsonSchemaError):
                scene_drafts.write_batch(
                    1, 3, [{"类型": "未知", "区域": "苏州", "场景": "废园"}],
                    self.save_dir,
                )
        self.assertEqual(scene_drafts.read_draft(1, self.save_dir)["operations"], self.operations)


if __name__ == "__main__":
    unittest.main()
