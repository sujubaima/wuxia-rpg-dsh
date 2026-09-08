#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON 权威状态、缓存与交换文件读取策略回归。"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from common import dao as dq
from common.json_io import JsonSchemaError, JsonSyntaxError
from store import battle_last, check_log, save_manager as sm, tips


class AuthoritativeJsonPolicyTest(unittest.TestCase):
    def test_missing_state_uses_defaults_but_corruption_is_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(sm.read_meta(1, directory))
            self.assertEqual(sm.read_explore(1, directory), {})

            slot = Path(directory) / "slot_1"
            slot.mkdir()
            explore = slot / "explore.json"
            explore.write_text('{"broken"', encoding="utf-8")

            with self.assertRaises(JsonSyntaxError):
                sm.read_explore(1, directory)
            before = explore.read_text(encoding="utf-8")
            with self.assertRaises(JsonSyntaxError):
                sm.write_explore(1, {"体力": 80}, directory)
            self.assertEqual(explore.read_text(encoding="utf-8"), before)

            explore.write_text("[]", encoding="utf-8")
            with self.assertRaises(JsonSchemaError):
                sm.read_explore(1, directory)

    def test_legacy_explore_and_save_state_are_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = Path(directory) / "slot_2"
            slot.mkdir()
            (slot / "explore.json").write_text(
                '{"当前位置":"苏州城·码头"}', encoding="utf-8"
            )
            save = slot / "savefile_20260101_010101.json"
            save.write_text(
                '{"state":{"当前时辰":"子时","人物状态":{}}}', encoding="utf-8"
            )

            self.assertEqual(sm.read_explore(2, directory)["当前位置"], "苏州·码头")
            state = sm.load(save.name, 2, directory)
            self.assertEqual(state["当前时间"], 0)
            self.assertEqual(state["体力"], sm.STAMINA_MAX)
            self.assertNotIn("当前时辰", state)

    def test_restore_validates_snapshot_before_touching_live_state(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = Path(directory) / "slot_5"
            data = slot / ".data" / "characters"
            data.mkdir(parents=True)
            marker = data / "保留.json"
            marker.write_text('{"名称":"保留"}', encoding="utf-8")
            explore = slot / "explore.json"
            explore.write_text('{"体力":70}', encoding="utf-8")
            save = slot / "savefile_20260101_010101.json"
            save.write_text(
                '{"state":{"人物状态":{}},"map_overlay":[]}', encoding="utf-8"
            )

            with self.assertRaises(JsonSchemaError):
                sm.restore(5, save.name, directory, data_dir=str(Path(directory) / "baseline"))
            self.assertEqual(marker.read_text(encoding="utf-8"), '{"名称":"保留"}')
            self.assertEqual(explore.read_text(encoding="utf-8"), '{"体力":70}')

    def test_corrupt_dao_index_falls_back_but_record_is_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "characters"
            group = base / "散人"
            group.mkdir(parents=True)
            (base / "index.json").write_text('{"broken"', encoding="utf-8")
            record = group / "甲.json"
            record.write_text('{"名称":"甲"}', encoding="utf-8")

            with self.assertLogs("common.json_io", level="WARNING") as logs:
                paths = dq._scan_dir("角色", str(base))
            self.assertEqual(paths["甲"], str(record))
            self.assertIn("json_syntax_error", logs.output[0])

            record.write_text('{"broken"', encoding="utf-8")
            with self.assertRaises(JsonSyntaxError):
                dq._read_file(str(record))


class RecoverableJsonPolicyTest(unittest.TestCase):
    def test_merchant_cache_warns_and_rebuilds(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = Path(directory) / "slot_3"
            slot.mkdir()
            (slot / "merchant.json").write_text("[]", encoding="utf-8")

            with self.assertLogs("common.json_io", level="WARNING") as logs:
                self.assertEqual(sm.read_merchant_cache(3, directory), {})
            self.assertIn("json_schema_error", logs.output[0])

    def test_exchange_files_warn_and_keep_empty_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = Path(directory) / "slot_4"
            slot.mkdir()
            for filename in ("tips.json", "battle_last.json", "check.json"):
                (slot / filename).write_text('{"broken"', encoding="utf-8")

            with patch.object(sm, "slot_path", side_effect=lambda n, save_dir=sm.DEFAULT_SAVE_DIR: str(Path(directory) / f"slot_{n}")), \
                    patch.object(sm, "read_round", return_value=0), \
                    self.assertLogs("common.json_io", level="WARNING") as logs:
                self.assertEqual(tips.read_tips(4), [])
                self.assertIsNone(battle_last.read_battle_last(4))
                self.assertEqual(check_log.missing_check_hints(4, "剧情"), [])
            text = "\n".join(logs.output)
            self.assertEqual(text.count("json_syntax_error"), 3)


class EngineCliJsonErrorTest(unittest.TestCase):
    def test_cli_returns_structured_json_read_error(self):
        with tempfile.TemporaryDirectory() as directory:
            slot = Path(directory) / "slot_1"
            slot.mkdir()
            (slot / "explore.json").write_text('{"broken"', encoding="utf-8")
            env = dict(os.environ, WUXIA_RPG_SAVE_DIR=directory)
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "engine.py"), "go"],
                input='{"槽位":1,"行为":[]}', text=True, capture_output=True,
                env=env, timeout=30,
            )

            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn('"错误代码": "json_syntax_error"', proc.stdout)
            self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
