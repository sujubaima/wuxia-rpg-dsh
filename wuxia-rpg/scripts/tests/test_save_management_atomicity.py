#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存档管理的提交隔离与目标槽位互斥回归。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from store import save_manager as sm, turn_workspace as ws  # noqa: E402
from tests.test_slot_allocation import character  # noqa: E402


class SaveManagementAtomicityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save_dir = self.temp.name
        self.env = {**os.environ, "WUXIA_RPG_SAVE_DIR": self.save_dir}
        sm.create_slot(character("测试甲"), 1, self.save_dir)
        first = sm.read_explore(1, self.save_dir)
        first.update({"当前位置": "长沙·橘子洲头", "当前剧情": "旧剧情", "场景要素": [
            {"主体": "旧景", "描写": "旧貌"}]})
        sm.write_explore(1, first, self.save_dir)
        sm.save(first, 1, self.save_dir, label="旧档")
        latest = sm.read_explore(1, self.save_dir)
        latest.update({"当前剧情": "新剧情", "场景要素": [
            {"主体": "新景", "描写": "新貌"}]})
        sm.write_explore(1, latest, self.save_dir)
        (Path(ws.slot_path(1, self.save_dir)) / "untouched.txt").write_text("committed", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, action, slot=1):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "engine.py"), "go"],
            input=json.dumps({"槽位": slot, "行为": [action]}, ensure_ascii=False),
            capture_output=True, text=True, env=self.env, timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def snapshot(self, slot=1):
        root = Path(ws.slot_path(slot, self.save_dir))
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
                if p.is_file()}

    def inject_failure(self, statement):
        code = ("import engine\nfrom store import save_manager as sm\n"
                "from unittest.mock import patch\n" + statement + "\n")
        return subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS,
                              capture_output=True, text=True, env=self.env, timeout=90)

    def test_restore_failure_does_not_modify_committed_generation(self):
        before = self.snapshot()
        failed = self.inject_failure(
            "with patch.object(sm, 'write_quest_state', side_effect=RuntimeError('mid-restore')):\n"
            "    engine.go(1, [{'类型':'加载存档','目标':'File_1'}])")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("mid-restore", failed.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(ws.pending_exists(1, self.save_dir))
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前剧情"], "新剧情")

    def test_restore_process_exit_does_not_corrupt_committed_slot(self):
        before = self.snapshot()
        interrupted = self.inject_failure(
            "import os\n"
            "rmtree = sm.shutil.rmtree\n"
            "def crash_after_delete(path, *args, **kwargs):\n"
            "    rmtree(path, *args, **kwargs)\n"
            "    if str(path).endswith('.data'): os._exit(73)\n"
            "with patch.object(sm.shutil, 'rmtree', side_effect=crash_after_delete):\n"
            "    engine.go(1, [{'类型':'加载存档','目标':'File_1'}])")
        self.assertEqual(interrupted.returncode, 73, interrupted.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(ws.pending_exists(1, self.save_dir))
        ws.abort_pending(1, self.save_dir)
        self.assertEqual(self.snapshot(), before)

    def test_restore_response_failure_does_not_publish(self):
        before = self.snapshot()
        failed = self.inject_failure(
            "with patch.object(engine, '_build_response', side_effect=RuntimeError('ui-failed')):\n"
            "    engine.go(1, [{'类型':'加载存档','目标':'File_1'}])")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("ui-failed", failed.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(ws.pending_exists(1, self.save_dir))

    def test_restore_success_publishes_complete_response(self):
        response = self.command({"类型": "加载存档", "目标": "File_1"})
        self.assertNotIn("错误", response)
        self.assertEqual(response["界面"], "exploration-ui")
        self.assertEqual(response["turn_state"], "READY")
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前剧情"], "旧剧情")
        self.assertEqual(ws.read_committed_response(1, self.save_dir), response)
        self.assertFalse(ws.pending_exists(1, self.save_dir))

    def test_invalid_restore_does_not_publish_empty_generation(self):
        before = self.snapshot()
        result = self.command({"类型": "加载存档", "目标": "不存在的存档"})
        self.assertTrue(result.get("错误") or result.get("提示"), result)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(ws.pending_exists(1, self.save_dir))

    def test_restore_rejects_pending_without_discarding_it(self):
        ws.begin_pending(1, self.save_dir)
        with ws.slot_view("pending"):
            sm.write_explore(1, {"当前剧情": "未完草稿"}, self.save_dir)
        before = self.snapshot()
        result = self.command({"类型": "加载存档", "目标": "File_1"})
        self.assertIn("错误", result)
        self.assertEqual(result["状态冲突"], "go_already_staged")
        self.assertTrue(ws.pending_exists(1, self.save_dir))
        self.assertEqual(self.snapshot(), before)
        with ws.slot_view("pending"):
            self.assertEqual(sm.read_explore(1, self.save_dir)["当前剧情"], "未完草稿")

    def test_cross_target_delete_rejects_pending_and_direct_api_rejects(self):
        sm.create_slot(character("测试乙"), 2, self.save_dir)
        sm.save(sm.read_explore(2, self.save_dir), 2, self.save_dir, label="乙档")
        ws.begin_pending(2, self.save_dir)
        active_before = self.snapshot(2)
        for action in ({"类型": "删除存档", "槽位": 2},
                       {"类型": "删除存档", "槽位": 2, "目标": "File_1"}):
            result = self.command(action, slot=1)
            self.assertIn("错误", result)
            self.assertEqual(self.snapshot(2), active_before)
        with self.assertRaises(sm.PendingSlotDeletionError):
            sm.delete_slot(2, self.save_dir)
        with self.assertRaises(sm.PendingSlotDeletionError):
            sm.delete_save(2, "File_1", self.save_dir)
        self.assertTrue(ws.pending_exists(2, self.save_dir))
        ws.abort_pending(2, self.save_dir)
        result = self.command({"类型": "删除存档", "槽位": 2, "目标": "File_1"}, slot=1)
        self.assertNotIn("错误", result)
        self.assertEqual(sm.list_saves(2, self.save_dir), [])

    def test_delete_waits_for_target_judge_lock(self):
        sm.create_slot(character("测试乙"), 2, self.save_dir)
        ws.begin_pending(2, self.save_dir)
        # A judge owns this lock until it commits; deletion must not race or erase its workspace.
        started = threading.Event()
        finished = threading.Event()
        results = []
        def delete():
            started.set()
            results.append(self.command({"类型": "删除存档", "槽位": 2}, slot=1))
            finished.set()
        with ws.slot_lock(2, self.save_dir):
            worker = threading.Thread(target=delete)
            worker.start()
            self.assertTrue(started.wait(5))
            self.assertFalse(finished.wait(0.3))
            self.assertTrue(ws.pending_exists(2, self.save_dir))
        worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertIn("错误", results[0])
        self.assertTrue(ws.pending_exists(2, self.save_dir))


if __name__ == "__main__":
    unittest.main()
