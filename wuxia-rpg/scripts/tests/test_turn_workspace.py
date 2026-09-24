#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""槽位待提交代目录、迁移与跨进程锁。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import dao as dq  # noqa: E402
from store import save_manager as sm, turn_state, turn_workspace as ws  # noqa: E402
from tests.test_slot_allocation import character  # noqa: E402


class TurnWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save_dir = self.temp.name
        self.root = ws.physical_slot_path(1, self.save_dir)
        os.makedirs(self.root)
        sm.write_meta(1, {"slot": 1, "角色名": "测试"}, self.save_dir)
        sm.write_explore(1, {"当前位置": "苏州"}, self.save_dir)

    def tearDown(self):
        dq.set_data_dir(dq.BASELINE_DATA_DIR)
        self.temp.cleanup()

    def test_legacy_migrates_and_pending_isolated_until_publish(self):
        pending = ws.begin_pending(1, self.save_dir)
        active = ws.slot_path(1, self.save_dir)
        self.assertNotEqual(pending, active)
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        with ws.slot_view("pending"):
            self.assertEqual(sm.slot_path(1, self.save_dir), pending)
            sm.write_explore(1, {"当前位置": "杭州"}, self.save_dir)
            self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "杭州")
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        self.assertEqual(sm.list_slots(self.save_dir)[0]["角色名"], "测试")
        ws.publish_pending(1, {"界面": "exploration-ui"}, self.save_dir)
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "杭州")
        self.assertEqual(ws.read_committed_response(1, self.save_dir), {"界面": "exploration-ui"})
        self.assertFalse(ws.pending_exists(1, self.save_dir))
        self.assertTrue(os.path.isdir(self.root))
        self.assertTrue(os.path.isdir(active))

    def test_abort_preserves_committed_files(self):
        ws.begin_pending(1, self.save_dir)
        with ws.slot_view("pending"):
            sm.write_explore(1, {"当前位置": "杭州"}, self.save_dir)
        self.assertTrue(ws.abort_pending(1, self.save_dir))
        self.assertFalse(ws.abort_pending(1, self.save_dir))
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        self.assertIsNone(ws.read_committed_response(1, self.save_dir))

    def test_legacy_unresolved_go_is_not_promoted_or_discarded(self):
        turn_state.write_state(1, turn_state.AWAITING_JUDGE, save_dir=self.save_dir)
        with self.assertRaises(ws.LegacyPendingTurnError):
            ws.begin_pending(1, self.save_dir)
        self.assertEqual(turn_state.read_state(1, self.save_dir)["state"], turn_state.AWAITING_JUDGE)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".runtime", "active_generation.json")))

    def test_dao_set_slot_and_direct_writes_route_to_pending(self):
        ws.begin_pending(1, self.save_dir)
        original = dq.SAVE_DIR
        try:
            dq.SAVE_DIR = self.save_dir
            with ws.slot_view("pending"):
                dq.set_slot(1)
                self.assertEqual(dq.DATA_DIR, os.path.join(ws.slot_path(1, self.save_dir), ".data"))
                path = os.path.join(sm.slot_path(1, self.save_dir), "map_overlay.json")
                with open(path, "w", encoding="utf-8") as file:
                    json.dump({"地图": "新"}, file)
            self.assertFalse(os.path.exists(os.path.join(ws.slot_path(1, self.save_dir), "map_overlay.json")))
            self.assertTrue(os.path.exists(path))
        finally:
            dq.SAVE_DIR = original
            dq.set_data_dir(dq.BASELINE_DATA_DIR)

    def test_new_slot_pending_invisible_until_publish(self):
        self.assertEqual(ws.current_view(), "active")
        with ws.slot_view("pending"):
            self.assertEqual(ws.current_view(), "pending")
        self.assertEqual(ws.current_view(), "active")
        sm.create_slot(character("待发布者"), 2, save_dir=self.save_dir, pending=True)
        with ws.slot_view("pending"):
            self.assertTrue(os.path.isdir(ws.slot_path(2, self.save_dir)))
        self.assertTrue(ws.pending_exists(2, self.save_dir))
        self.assertFalse(ws.active_exists(2, self.save_dir))
        with self.assertRaises(ws.PendingWorkspaceError):
            ws.slot_path(2, self.save_dir)
        self.assertEqual([row["slot"] for row in sm.list_slots(self.save_dir)], [1])
        self.assertEqual(sm.list_all_saves(self.save_dir)[0]["slot"], 1)
        self.assertEqual(sm.next_slot_number(self.save_dir), 3)
        with ws.slot_view("pending"):
            self.assertEqual(sm.read_meta(2, self.save_dir)["角色名"], "待发布者")
            self.assertIsNotNone(dq.read_character_file(
                "待发布者", data_dir=sm.slot_data_dir(2, self.save_dir)))
        with self.assertRaises(sm.SlotOccupiedError):
            sm.create_slot(character("其他人"), 2, save_dir=self.save_dir, pending=True)
        ws.publish_pending(2, {"界面": "exploration-ui"}, self.save_dir)
        self.assertTrue(ws.active_exists(2, self.save_dir))
        self.assertEqual(sm.read_meta(2, self.save_dir)["角色名"], "待发布者")
        self.assertEqual(ws.read_committed_response(2, self.save_dir), {"界面": "exploration-ui"})

    def test_pre_reserved_slot_initializes_without_publishing(self):
        generation = ws.begin_new_pending(3, self.save_dir)
        with self.assertRaises(FileExistsError):
            ws.begin_new_pending(3, self.save_dir)
        with ws.slot_view("pending"):
            sm.create_slot(character("先占后建"), 3, save_dir=self.save_dir, pending=True)
            self.assertEqual(ws.slot_path(3, self.save_dir), generation)
            self.assertEqual(sm.read_meta(3, self.save_dir)["角色名"], "先占后建")
        self.assertFalse(ws.active_exists(3, self.save_dir))
        with self.assertRaises(sm.SlotOccupiedError):
            sm.create_slot(character("第二个"), 3, save_dir=self.save_dir, pending=True)
        with ws.slot_view("pending"):
            self.assertEqual(sm.read_meta(3, self.save_dir)["角色名"], "先占后建")
        ws.publish_pending(3, {"ok": True}, self.save_dir)
        self.assertTrue(ws.active_exists(3, self.save_dir))

    def test_new_slot_crash_before_rename_does_not_reserve_slot(self):
        script = (
            "import os, sys; from store import turn_workspace as ws; "
            "\nwrite = ws._write_pointer\n"
            "def crash(root, filename, generation):\n"
            " write(root, filename, generation); os._exit(46)\n"
            "ws._write_pointer = crash\n"
            "ws.begin_new_pending(2, sys.argv[1])\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", script, self.save_dir],
            env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
            capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(child.returncode, 46, child.stderr)
        self.assertFalse(os.path.exists(ws.physical_slot_path(2, self.save_dir)))
        self.assertEqual(sm.next_slot_number(self.save_dir), 2)
        self.assertTrue(any(name.startswith(".slot_2_building_")
                            for name in os.listdir(self.save_dir)))
        ws.begin_new_pending(2, self.save_dir)
        self.assertTrue(ws.pending_exists(2, self.save_dir))
        self.assertFalse(any(name.startswith(".slot_2_building_")
                             for name in os.listdir(self.save_dir)))

    def test_new_slot_crash_after_rename_leaves_valid_pending(self):
        script = (
            "import os, sys; from store import turn_workspace as ws; "
            "\nrename = os.rename\n"
            "def crash(source, destination):\n"
            " rename(source, destination); os._exit(47)\n"
            "os.rename = crash\n"
            "ws.begin_new_pending(2, sys.argv[1])\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", script, self.save_dir],
            env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
            capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(child.returncode, 47, child.stderr)
        self.assertTrue(ws.pending_exists(2, self.save_dir))
        with self.assertRaises(FileExistsError):
            ws.begin_new_pending(2, self.save_dir)
        self.assertTrue(ws.abort_pending(2, self.save_dir))
        self.assertEqual(sm.next_slot_number(self.save_dir), 2)

    def test_new_slot_abort_and_failed_initialization(self):
        pending = ws.begin_new_pending(2, self.save_dir)
        self.assertTrue(os.path.isdir(pending))
        self.assertFalse(ws.active_exists(2, self.save_dir))
        self.assertTrue(ws.abort_pending(2, self.save_dir))
        self.assertFalse(os.path.exists(pending))
        self.assertFalse(os.path.exists(ws.physical_slot_path(2, self.save_dir)))
        self.assertEqual(sm.next_slot_number(self.save_dir), 2)
        with mock.patch.object(sm, "write_meta", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                sm.create_slot(character("未建成"), 3, save_dir=self.save_dir, pending=True)
        self.assertFalse(os.path.exists(ws.physical_slot_path(3, self.save_dir)))
        ws.begin_new_pending(4, self.save_dir)
        sm.create_slot(character("取消开局"), 4, save_dir=self.save_dir, pending=True)
        self.assertTrue(ws.abort_pending(4, self.save_dir))
        self.assertFalse(os.path.exists(ws.physical_slot_path(4, self.save_dir)))
        self.assertEqual(sm.next_slot_number(self.save_dir), 2)

    def test_trial_and_publish_sync_before_pointer_switches(self):
        ws.begin_pending(1, self.save_dir)
        events = []
        sync = ws._sync_generation
        write = ws._write_pointer

        def record_sync(root, generation):
            sync(root, generation)
            events.append(("sync", generation))

        def record_pointer(root, filename, name):
            if filename == ws._ACTIVE:
                response = os.path.join(root, ".generations", name,
                                        ".runtime", "committed_response.json")
                self.assertTrue(os.path.isfile(response))
                with open(response, encoding="utf-8") as file:
                    self.assertEqual(json.load(file), {"ok": True})
            events.append(("pointer", filename))
            write(root, filename, name)

        with mock.patch.object(ws, "_sync_generation", side_effect=record_sync), \
             mock.patch.object(ws, "_write_pointer", side_effect=record_pointer):
            with ws.pending_trial(1, self.save_dir) as trial:
                trial.commit()
                ws.publish_pending(1, {"ok": True}, self.save_dir)
        self.assertEqual(events[0][0], "sync")
        active_pointer = events.index(("pointer", ws._ACTIVE))
        self.assertGreaterEqual(active_pointer, 2)
        self.assertEqual(events[active_pointer - 1][0], "sync")

    def test_publish_sync_failure_keeps_old_active(self):
        ws.begin_pending(1, self.save_dir)
        with ws.slot_view("pending"):
            sm.write_explore(1, {"当前位置": "杭州"}, self.save_dir)
        with mock.patch.object(ws, "fsync_tree", side_effect=OSError("sync failed")):
            with self.assertRaisesRegex(OSError, "sync failed"):
                ws.publish_pending(1, {"ok": True}, self.save_dir)
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        self.assertTrue(ws.pending_exists(1, self.save_dir))
        ws.publish_pending(1, {"ok": True}, self.save_dir)
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "杭州")

    def test_pointer_write_error_after_swap_preserves_referenced_generations(self):
        write = ws._write_pointer

        def fail_after_write(root, filename, generation):
            write(root, filename, generation)
            raise OSError("post-swap sync failed")

        with mock.patch.object(ws, "_write_pointer", side_effect=fail_after_write):
            with self.assertRaisesRegex(OSError, "post-swap sync failed"):
                ws.begin_pending(1, self.save_dir)
        # Legacy migration's active pointer already switched and must still resolve.
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        self.assertIsNotNone(ws._pointer(self.root, ws._ACTIVE))

        with mock.patch.object(ws, "_write_pointer", side_effect=fail_after_write):
            with self.assertRaisesRegex(OSError, "post-swap sync failed"):
                ws.begin_pending(1, self.save_dir)
        # Pending pointer already switched and must still be reusable.
        self.assertTrue(ws.pending_exists(1, self.save_dir))
        with ws.slot_view("pending"):
            self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        self.assertTrue(ws.abort_pending(1, self.save_dir))

    def test_pending_trial_rollback_and_commit(self):
        original = ws.begin_pending(1, self.save_dir)
        with ws.pending_trial(1, self.save_dir):
            self.assertNotEqual(ws.slot_path(1, self.save_dir), original)
            sm.write_explore(1, {"当前位置": "杭州"}, self.save_dir)
        with ws.slot_view("pending"):
            self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
            self.assertEqual(ws.slot_path(1, self.save_dir), original)
        with self.assertRaisesRegex(RuntimeError, "retry"):
            with ws.pending_trial(1, self.save_dir) as trial:
                trial.commit()
                sm.write_explore(1, {"当前位置": "泉州"}, self.save_dir)
                raise RuntimeError("retry")
        with ws.slot_view("pending"):
            self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        with ws.pending_trial(1, self.save_dir) as trial:
            sm.write_explore(1, {"当前位置": "杭州"}, self.save_dir)
            with ws.slot_view("pending"):
                self.assertNotEqual(ws.slot_path(1, self.save_dir), original)
            self.assertEqual(json.loads(Path(self.root, ".runtime", "pending_generation.json")
                                        .read_text(encoding="utf-8"))["generation"],
                             os.path.basename(original))
            trial.commit()
            ws.publish_pending(1, {"ok": True}, self.save_dir)
            with self.assertRaises(ws.PendingWorkspaceError):
                ws.slot_path(1, self.save_dir)
        self.assertFalse(os.path.exists(original))
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "杭州")

    def test_crash_mid_trial_keeps_original_pending_reusable(self):
        original = ws.begin_pending(1, self.save_dir)
        script = (
            "import os, sys; from store import turn_workspace as ws; "
            "from store import save_manager as sm; "
            "\nwith ws.pending_trial(1, sys.argv[1]):\n"
            " sm.write_explore(1, {'当前位置': '损坏的半轮'}, sys.argv[1]); os._exit(43)\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", script, self.save_dir],
            env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
            capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(child.returncode, 43, child.stderr)
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        self.assertTrue(ws.pending_exists(1, self.save_dir))
        with ws.slot_view("pending"):
            self.assertEqual(ws.slot_path(1, self.save_dir), original)
            self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        with ws.pending_trial(1, self.save_dir) as trial:
            sm.write_explore(1, {"当前位置": "安全重试"}, self.save_dir)
            trial.commit()
            ws.publish_pending(1, {"ok": True}, self.save_dir)
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "安全重试")

    def test_crash_before_active_swap_preserves_original_pending(self):
        original = ws.begin_pending(1, self.save_dir)
        script = (
            "import os, sys; from store import turn_workspace as ws; "
            "from store import save_manager as sm; "
            "\nwrite = ws._write_pointer\n"
            "def crash(root, filename, generation):\n"
            " if filename == ws._ACTIVE:\n"
            "  assert os.path.isfile(ws._manifest(ws._generation(root, generation), ws._RESPONSE))\n"
            "  os._exit(45)\n"
            " write(root, filename, generation)\n"
            "ws._write_pointer = crash\n"
            "with ws.pending_trial(1, sys.argv[1]) as trial:\n"
            " sm.write_explore(1, {'当前位置': '未提交'}, sys.argv[1])\n"
            " trial.commit()\n"
            " ws.publish_pending(1, {'ok': True}, sys.argv[1])\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", script, self.save_dir],
            env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
            capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(child.returncode, 45, child.stderr)
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        self.assertIsNone(ws.read_committed_response(1, self.save_dir))
        self.assertTrue(ws.pending_exists(1, self.save_dir))
        with ws.slot_view("pending"):
            self.assertEqual(ws.slot_path(1, self.save_dir), original)
            self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "苏州")
        with ws.pending_trial(1, self.save_dir) as trial:
            sm.write_explore(1, {"当前位置": "安全重试"}, self.save_dir)
            trial.commit()
            ws.publish_pending(1, {"ok": "retry"}, self.save_dir)
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "安全重试")
        self.assertEqual(ws.read_committed_response(1, self.save_dir), {"ok": "retry"})

    def test_crash_after_active_swap_recognizes_stale_original_pending(self):
        original = ws.begin_pending(1, self.save_dir)
        script = (
            "import os, sys; from store import turn_workspace as ws; "
            "from store import save_manager as sm; "
            "\nwrite = ws._write_pointer\n"
            "def crash(root, filename, generation):\n"
            " write(root, filename, generation)\n"
            " if filename == ws._ACTIVE: os._exit(44)\n"
            "ws._write_pointer = crash\n"
            "with ws.pending_trial(1, sys.argv[1]) as trial:\n"
            " sm.write_explore(1, {'当前位置': '已提交'}, sys.argv[1])\n"
            " trial.commit()\n"
            " ws.publish_pending(1, {'ok': True}, sys.argv[1])\n"
        )
        child = subprocess.run(
            [sys.executable, "-c", script, self.save_dir],
            env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
            capture_output=True, text=True, check=False, timeout=20,
        )
        self.assertEqual(child.returncode, 44, child.stderr)
        self.assertTrue(os.path.isdir(original))
        self.assertEqual(sm.read_explore(1, self.save_dir)["当前位置"], "已提交")
        self.assertEqual(ws.read_committed_response(1, self.save_dir), {"ok": True})
        self.assertFalse(ws.pending_exists(1, self.save_dir))
        with ws.slot_view("pending"):
            with self.assertRaises(ws.PendingWorkspaceError):
                ws.slot_path(1, self.save_dir)
        with self.assertRaises(ws.PendingWorkspaceError):
            with ws.pending_trial(1, self.save_dir):
                pass
        ws.begin_pending(1, self.save_dir)
        self.assertFalse(os.path.exists(original))
        self.assertTrue(ws.pending_exists(1, self.save_dir))

    def test_lock_excludes_other_process_and_allows_nested_calls(self):
        script = (
            "import sys; from store.turn_workspace import slot_lock; "
            "slot=int(sys.argv[1]); save_dir=sys.argv[2]; "
            "\ntry:\n with slot_lock(slot, save_dir, blocking=False): pass\n"
            "except BlockingIOError: sys.exit(7)\n"
        )
        with ws.slot_lock(1, self.save_dir):
            with ws.slot_lock(1, self.save_dir):
                child = subprocess.run(
                    [sys.executable, "-c", script, "1", self.save_dir],
                    env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(child.returncode, 7, child.stderr)
        child = subprocess.run(
            [sys.executable, "-c", script, "1", self.save_dir],
            env={**os.environ, "PYTHONPATH": str(SCRIPTS)},
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_locking_missing_slot_does_not_create_slot(self):
        with ws.slot_lock(2, self.save_dir):
            pass
        self.assertFalse(os.path.exists(ws.physical_slot_path(2, self.save_dir)))
        self.assertEqual(sm.next_slot_number(self.save_dir), 2)

    def test_delete_slot_removes_all_generations(self):
        ws.begin_pending(1, self.save_dir)
        ws.publish_pending(1, {"界面": "exploration-ui"}, self.save_dir)
        sm.delete_slot(1, self.save_dir)
        self.assertFalse(os.path.exists(self.root))


if __name__ == "__main__":
    unittest.main()
