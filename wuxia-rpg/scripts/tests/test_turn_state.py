#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正式 slot 的 go/judge 阶段状态持久化。"""

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
from store import turn_state  # noqa: E402


class TurnStateStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save_dir = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_state_defaults_to_ready(self):
        self.assertEqual(
            turn_state.read_state(1, self.save_dir),
            turn_state.ready_state(),
        )

    def test_state_round_trip_and_reset(self):
        expected = turn_state.write_state(
            2,
            turn_state.AWAITING_JUDGE,
            origin="普通行动",
            go_result={"结算": [{"ok": True}]},
            save_dir=self.save_dir,
        )
        self.assertEqual(turn_state.read_state(2, self.save_dir), expected)

        reset = turn_state.reset_state(2, self.save_dir)
        self.assertEqual(reset["state"], turn_state.READY)
        self.assertEqual(reset["go_result"], {})
        self.assertEqual(turn_state.read_state(2, self.save_dir), reset)

    def test_slot_zero_never_writes_state(self):
        state = turn_state.write_state(
            0,
            turn_state.AWAITING_JUDGE,
            go_result={"ok": True},
            save_dir=self.save_dir,
        )
        self.assertEqual(state["state"], turn_state.READY)
        self.assertFalse(os.path.exists(os.path.join(self.save_dir, "slot_0")))
        self.assertEqual(turn_state.read_state(0, self.save_dir)["state"], turn_state.READY)

    def test_corrupt_state_is_not_silently_reset(self):
        path = turn_state.turn_state_path(3, self.save_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write("{")
        with self.assertRaises(JsonSyntaxError):
            turn_state.read_state(3, self.save_dir)

        with open(path, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "state": "BROKEN"}, file)
        with self.assertRaises(JsonSchemaError):
            turn_state.read_state(3, self.save_dir)


if __name__ == "__main__":
    unittest.main()
