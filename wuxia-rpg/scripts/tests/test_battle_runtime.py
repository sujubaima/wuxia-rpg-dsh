#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战斗 runtime 路径、读写与清理回归。"""

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

from combat import battle
from store import battle_runtime as br


class BattleRuntimeTest(unittest.TestCase):
    def test_slot_and_debug_runtime_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            save_root = os.path.join(directory, "save")
            debug_root = os.path.join(directory, "debug")
            with patch.object(br.dq, "SAVE_DIR", save_root):
                self.assertEqual(
                    br.state_path(7),
                    os.path.join(save_root, "slot_7", ".runtime", "battle", "battle_state.json"),
                )
            with patch.dict(os.environ, {"WUXIA_RPG_RUNTIME_DIR": debug_root}):
                self.assertEqual(
                    br.meta_path(),
                    os.path.join(debug_root, "battle", "battle_meta.json"),
                )
            with patch.dict(os.environ, {"WUXIA_RPG_RUNTIME_DIR": ""}), \
                    patch.object(br.tempfile, "gettempdir", return_value=directory):
                self.assertEqual(
                    br.report_path(),
                    os.path.join(directory, "wuxia-rpg-runtime", "battle", "battle_report.json"),
                )

    def test_battle_writes_and_reads_slot_runtime(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(br.dq, "SAVE_DIR", directory):
            state = {"角色列表": [], "回合数": 3}
            battle.save_state(state, 2)
            battle.save_meta(3, ["甲"], 2, allow_escape=True)
            with patch.object(battle.dq, "get_field", return_value=(None, "人设")):
                battle.emit_roster_ref([{"名称": "甲"}], 2)

            runtime = Path(directory) / "slot_2" / ".runtime" / "battle"
            self.assertEqual(battle.load_state(2), state)
            self.assertTrue(battle.load_meta(2)["allow_escape"])
            self.assertEqual(
                json.loads((runtime / "battle_report.json").read_text(encoding="utf-8")),
                {"人设参考": [{"名称": "甲", "人设": " " * 500 + "人设"}]},
            )
            self.assertEqual(
                {path.name for path in runtime.iterdir()},
                {"battle_state.json", "battle_meta.json", "battle_report.json"},
            )

    def test_reads_legacy_runtime_when_new_file_is_absent(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(br.dq, "SAVE_DIR", os.path.join(directory, "save")), \
                patch.object(br, "LEGACY_DIR", os.path.join(directory, "legacy")):
            legacy = Path(br.LEGACY_DIR)
            legacy.mkdir()
            (legacy / "battle_state_slot4.json").write_text(
                '{"角色列表": [], "回合数": 8}', encoding="utf-8"
            )
            (legacy / "battle_meta_slot4.json").write_text(
                '{"n": 8, "player": "甲", "slot": 4}', encoding="utf-8"
            )

            self.assertEqual(battle.load_state(4)["回合数"], 8)
            self.assertEqual(battle.load_meta(4)["players"], ["甲"])
            self.assertTrue(br.battle_exists(4))

    def test_clear_removes_only_battle_runtime_and_legacy_files(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(br.dq, "SAVE_DIR", os.path.join(directory, "save")), \
                patch.object(br, "LEGACY_DIR", os.path.join(directory, "legacy")):
            slot = Path(br.dq.slot_path(3))
            runtime = Path(br.runtime_dir(3))
            runtime.mkdir(parents=True)
            marker = slot / "meta.json"
            marker.write_text("保留", encoding="utf-8")
            legacy = Path(br.LEGACY_DIR)
            legacy.mkdir()
            for filename in br.FILENAMES:
                (runtime / filename).write_text("{}", encoding="utf-8")
                Path(br.legacy_path(filename, 3)).write_text("{}", encoding="utf-8")

            br.clear(3)

            self.assertFalse(runtime.exists())
            self.assertTrue(marker.is_file())
            self.assertEqual(list(legacy.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
