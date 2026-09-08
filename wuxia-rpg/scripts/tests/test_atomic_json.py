#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON 原子写入回归。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from common import json_io


class AtomicJsonTest(unittest.TestCase):
    def test_writes_unicode_and_preserves_format_options(self):
        with tempfile.TemporaryDirectory() as directory:
            compact = Path(directory) / "compact.json"
            pretty = Path(directory) / "nested" / "pretty.json"
            value = {"名称": "张三", "数值": 1}

            with patch.object(json_io.os, "fsync", wraps=os.fsync) as fsync:
                json_io.atomic_write_json(compact, value)
            json_io.atomic_write_json(pretty, value, indent=2)

            self.assertEqual(compact.read_text(encoding="utf-8"), '{"名称": "张三", "数值": 1}')
            self.assertIn('\n  "名称": "张三"', pretty.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(pretty.read_text(encoding="utf-8")), value)
            fsync.assert_called_once()
            self.assertEqual(sorted(Path(directory).rglob("*")), [compact, pretty.parent, pretty])

    def test_serialization_failure_keeps_old_target_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            target.write_text('{"old": true}', encoding="utf-8")

            def fail(value, file, **kwargs):
                file.write('{"broken"')
                raise RuntimeError("serialize failed")

            with patch.object(json_io.json, "dump", side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, "serialize failed"):
                    json_io.atomic_write_json(target, {"new": True})

            self.assertEqual(target.read_text(encoding="utf-8"), '{"old": true}')
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_replace_failure_keeps_old_target_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            target.write_text('{"old": true}', encoding="utf-8")

            with patch.object(json_io.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    json_io.atomic_write_json(target, {"new": True})

            self.assertEqual(target.read_text(encoding="utf-8"), '{"old": true}')
            self.assertEqual(list(Path(directory).iterdir()), [target])


class JsonReadTest(unittest.TestCase):
    def test_reads_valid_json_and_checks_top_level_type(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"名称": "张三"}', encoding="utf-8")

            self.assertEqual(json_io.read_json(path, expected_type=dict), {"名称": "张三"})
            with self.assertRaises(json_io.JsonSchemaError) as ctx:
                json_io.read_json(path, expected_type=list)
            self.assertEqual(ctx.exception.code, "json_schema_error")
            self.assertEqual(ctx.exception.path, str(path))

    def test_classifies_missing_access_encoding_and_syntax_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.json"
            with self.assertRaises(json_io.JsonMissingError) as ctx:
                json_io.read_json(missing)
            self.assertEqual(ctx.exception.code, "json_missing")

            path = root / "state.json"
            path.write_bytes(b"\xff")
            with self.assertRaises(json_io.JsonEncodingError) as ctx:
                json_io.read_json(path)
            self.assertEqual(ctx.exception.code, "json_encoding_error")

            path.write_text('{"broken"', encoding="utf-8")
            with self.assertRaises(json_io.JsonSyntaxError) as ctx:
                json_io.read_json(path)
            self.assertEqual(ctx.exception.code, "json_syntax_error")

            with patch("builtins.open", side_effect=PermissionError("denied")):
                with self.assertRaises(json_io.JsonAccessError) as ctx:
                    json_io.read_json(path)
            self.assertEqual(ctx.exception.code, "json_io_error")

    def test_warn_json_read_records_category(self):
        error = json_io.JsonSyntaxError("broken.json", "测试损坏")
        with self.assertLogs("common.json_io", level="WARNING") as logs:
            json_io.warn_json_read(error)
        self.assertIn("json_syntax_error", logs.output[0])
        self.assertIn("broken.json", logs.output[0])


if __name__ == "__main__":
    unittest.main()
