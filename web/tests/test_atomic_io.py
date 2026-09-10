#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 本地状态与数据备份原子写入。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import atomic_io
import data_admin
import server
from atomic_io import atomic_write_json, atomic_write_text


class AtomicIoTest(unittest.TestCase):
    def test_writes_unicode_text_and_json(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = Path(directory) / "text.json"
            json_path = Path(directory) / "state.json"

            atomic_write_text(text_path, '{"名称":"张三"}')
            atomic_write_json(json_path, ["会话甲", "session-b"])

            self.assertEqual(text_path.read_text(encoding="utf-8"), '{"名称":"张三"}')
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), ["会话甲", "session-b"])

    def test_replace_failure_keeps_old_target_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            target.write_text('{"old":true}', encoding="utf-8")

            with patch.object(atomic_io.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    atomic_write_json(target, {"new": True})

            self.assertEqual(target.read_text(encoding="utf-8"), '{"old":true}')
            self.assertEqual(list(Path(directory).glob(".state.json.*.tmp")), [])


class WebStateAtomicWriteTest(unittest.TestCase):
    def test_sessions_state_uses_atomic_json_writer(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(server, "_STATE", os.path.join(directory, ".sessions.json")), \
                patch.object(server, "_known", {"session-b", "session-a"}):
            server._save_state()

            with open(server._STATE, encoding="utf-8") as file:
                self.assertEqual(json.load(file), ["session-a", "session-b"])

    def test_data_admin_backup_uses_atomic_text_writer(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(data_admin, "BACKUP_DIR", os.path.join(directory, "backups")), \
                patch.object(data_admin.time, "strftime", return_value="20260909_140000"):
            source = Path(directory) / "张三.json"
            source.write_text('{"名称":"张三"}', encoding="utf-8")

            data_admin._backup_existing(str(source), "角色", "张三")
            data_admin._backup_existing(str(source), "角色", "张三", deleted=True)

            backup_dir = Path(directory) / "backups" / "角色"
            self.assertEqual(
                (backup_dir / "张三.20260909_140000.json").read_text(encoding="utf-8"),
                '{"名称":"张三"}',
            )
            self.assertEqual(
                (backup_dir / "张三.20260909_140000.deleted.json").read_text(encoding="utf-8"),
                '{"名称":"张三"}',
            )


if __name__ == "__main__":
    unittest.main()
