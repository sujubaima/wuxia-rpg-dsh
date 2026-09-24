#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实 engine CLI 跨进程回合：go → plot-writing → judge 的提交隔离和恢复。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from engine import OPENING_ERA_TEMPLATE  # noqa: E402
from store import save_manager as sm, turn_state, turn_workspace as ws  # noqa: E402
from tests.test_slot_allocation import character  # noqa: E402
from world import scene as sc  # noqa: E402

ENGINE = SCRIPTS / "engine.py"
ELEMENTS = [{"主体": "四周", "描写": "一切如常"}]


def files_in(view):
    """Compare actual save-file contents, excluding runtime pointers and old generations."""
    root = Path(view)
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not set(path.relative_to(root).parts) & {".runtime", ".generations"}
    }


class NarrativeRefactorE2ETest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save_dir = self.temp.name
        self.slot = 1

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, command, **payload):
        proc = subprocess.run(
            [sys.executable, str(ENGINE), command],
            input=json.dumps({"槽位": self.slot, **payload}, ensure_ascii=False),
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "WUXIA_RPG_SAVE_DIR": self.save_dir},
        )
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"{command} did not return JSON (exit {proc.returncode}):\n"
                      f"stdout={proc.stdout}\nstderr={proc.stderr}")
        self.assertIn(proc.returncode, (0, 2), (result, proc.stderr))
        return result

    def existing_slot(self):
        sm.create_slot(character("试剑客"), self.slot, save_dir=self.save_dir)
        explore = sm.read_explore(self.slot, self.save_dir)
        explore["当前位置"] = "长沙·橘子洲头"
        sm.write_explore(self.slot, explore, self.save_dir)
        self.assertEqual(turn_state.read_state(self.slot, self.save_dir)["state"], turn_state.READY)

    def plot(self, story="一阵风掠过竹林。", actions=None, **extra):
        with ws.slot_view("pending"):
            region, _, scene = (sm.read_explore(self.slot, self.save_dir) or {})["当前位置"].partition("·")
        scene_info = (sc.load_scenes().get("场景类型", {}).get(region, {}) or {}).get(scene)
        kind = scene_info.get("类型") if isinstance(scene_info, dict) else scene_info
        npc = scene_info.get("功能NPC") if isinstance(scene_info, dict) else None
        commands = {"驿站": ["远行（舟车）"], "店铺": ["购买", "出售"],
                    "客栈": ["投宿"]}.get(kind)
        elements = ([{"主体": npc, "描写": "当值", "特殊指令": [
            {"名称": command, "可用": True} for command in commands]}]
                    if npc and commands else ELEMENTS)
        return self.run_command("plot-writing", 行为=actions or [], 当前剧情=story,
                                场景要素=elements, 提及地点=[], **extra)

    def active_files(self):
        return files_in(ws.slot_path(self.slot, self.save_dir))

    def pending_files(self):
        with ws.slot_view("pending"):
            return files_in(ws.slot_path(self.slot, self.save_dir))

    def test_existing_slot_go_plot_judge_publishes_only_after_judge(self):
        self.existing_slot()
        before = self.active_files()
        before_explore = sm.read_explore(self.slot, self.save_dir)
        before_round = sm.read_round(self.slot, self.save_dir)
        go = self.run_command("go", 行为=[{"类型": "其他行为", "描述": "查看竹林"}])
        self.assertNotIn("错误", go)
        self.assertEqual(go.get("turn_state"), turn_state.AWAITING_PLOT)
        self.assertIsNone(go.get("界面"))
        self.assertEqual(self.active_files(), before)
        self.assertEqual(sm.read_explore(self.slot, self.save_dir), before_explore)
        self.assertEqual(sm.read_round(self.slot, self.save_dir), before_round)
        self.assertIsNone(ws.read_committed_response(self.slot, self.save_dir))
        self.assertTrue(ws.pending_exists(self.slot, self.save_dir))
        query = self.run_command("go", 行为=[{"类型": "角色信息", "角色": "试剑客"}])
        self.assertEqual(query.get("turn_state"), turn_state.AWAITING_PLOT)
        self.assertEqual(self.active_files(), before)
        with ws.slot_view("pending"):
            self.assertNotEqual(sm.read_explore(self.slot, self.save_dir), before_explore)
        premature = self.run_command("judge")
        self.assertIn("错误", premature)
        self.assertEqual(premature.get("turn_state"), turn_state.AWAITING_PLOT)
        self.assertEqual(self.active_files(), before)

        plot = self.plot()
        self.assertNotIn("错误", plot)
        self.assertEqual(plot.get("turn_state"), turn_state.AWAITING_JUDGE)
        query = self.run_command("go", 行为=[{"类型": "角色信息", "角色": "试剑客"}])
        self.assertEqual(query.get("turn_state"), turn_state.AWAITING_JUDGE)
        self.assertEqual(self.active_files(), before)
        # The proposal is not a committed (or staged mechanism) mutation before judge.
        with ws.slot_view("pending"):
            self.assertNotEqual((sm.read_explore(self.slot, self.save_dir) or {}).get("当前剧情"),
                                "一阵风掠过竹林。")
        judged = self.run_command("judge")
        self.assertNotIn("错误", judged)
        self.assertEqual(judged.get("turn_state"), turn_state.READY)
        self.assertEqual(sm.read_explore(self.slot, self.save_dir)["当前剧情"], "一阵风掠过竹林。")
        self.assertEqual(sm.read_round(self.slot, self.save_dir), before_round + 1)
        self.assertEqual(ws.read_committed_response(self.slot, self.save_dir), judged)
        self.assertFalse(ws.pending_exists(self.slot, self.save_dir))

    def test_plot_error_does_not_destroy_pending_go_or_committed_state(self):
        self.existing_slot()
        before = self.active_files()
        go = self.run_command("go", 行为=[{"类型": "其他行为", "描述": "观察周围"}])
        self.assertNotIn("错误", go)
        pending = self.pending_files()
        rejected = self.run_command("plot-writing", 行为=[], 当前剧情="第一稿", 场景要素=[], 提及地点=[])
        self.assertIn("错误", rejected)
        self.assertEqual(rejected.get("turn_state"), turn_state.AWAITING_PLOT)
        self.assertEqual(self.pending_files(), pending)
        self.assertEqual(self.active_files(), before)
        corrected = self.plot(story="第二稿获准。")
        self.assertNotIn("错误", corrected)
        committed = self.run_command("judge")
        self.assertNotIn("错误", committed)
        self.assertEqual(sm.read_explore(self.slot, self.save_dir)["当前剧情"], "第二稿获准。")

    def test_plot_mutation_validation_failure_rolls_back_first_valid_change(self):
        self.existing_slot()
        before = self.active_files()
        go = self.run_command("go", 行为=[{"类型": "其他行为", "描述": "查看石桥"}])
        self.assertNotIn("错误", go)
        pending = self.pending_files()
        failed = self.plot(actions=[
            {"类型": "铜钱", "操作": "加", "角色": "试剑客", "值": 100},
            {"类型": "不存在类型", "值": 1},
        ])
        self.assertIn("错误", failed)
        self.assertEqual(failed.get("turn_state"), turn_state.AWAITING_PLOT)
        self.assertEqual(self.pending_files(), pending)
        self.assertEqual(self.active_files(), before)
        self.assertNotIn("错误", self.plot(story="改正后的桥边见闻。"))
        self.assertNotIn("错误", self.run_command("judge"))
        self.assertEqual(sm.read_explore(self.slot, self.save_dir)["当前剧情"], "改正后的桥边见闻。")

    def test_judge_error_retries_without_replaying_go_or_corrupting_pending(self):
        self.existing_slot()
        before = self.active_files()
        go = self.run_command("go", 行为=[{"类型": "其他行为", "描述": "察看竹林"}])
        self.assertNotIn("错误", go)
        self.assertNotIn("错误", self.plot())
        pending = self.pending_files()
        # A pending ordinary judge rejects the old direct mutation payload.
        rejected = self.run_command("judge", 行为=[{"类型": "铜钱", "操作": "加", "值": 100}],
                                    当前剧情="不应提交的剧情")
        self.assertIn("错误", rejected)
        self.assertEqual(rejected.get("turn_state"), turn_state.AWAITING_JUDGE)
        self.assertEqual(self.pending_files(), pending)
        self.assertEqual(self.active_files(), before)
        self.assertTrue(ws.pending_exists(self.slot, self.save_dir))
        committed = self.run_command("judge")
        self.assertNotIn("错误", committed)
        self.assertEqual(sm.read_explore(self.slot, self.save_dir)["当前剧情"], "一阵风掠过竹林。")

    def test_successful_plot_is_locked_and_original_draft_is_committed(self):
        self.existing_slot()
        before = self.active_files()
        self.assertNotIn("错误", self.run_command(
            "go", 行为=[{"类型": "其他行为", "描述": "驻足观望"}]))
        accepted = self.plot(story="记下桥边风声。")
        self.assertNotIn("错误", accepted)
        with ws.slot_view("pending"):
            draft_path = Path(ws.slot_path(self.slot, self.save_dir), ".runtime", "plot_draft.json")
            original = draft_path.read_bytes()
        pending = self.pending_files()

        rejected = self.plot(story="不得覆盖的第二稿。")
        self.assertEqual(rejected.get("状态冲突"), "plot_already_completed")
        self.assertEqual(rejected.get("turn_state"), turn_state.AWAITING_JUDGE)
        self.assertEqual(self.pending_files(), pending)
        self.assertEqual(self.active_files(), before)
        with ws.slot_view("pending"):
            self.assertEqual(draft_path.read_bytes(), original)

        self.assertNotIn("错误", self.run_command("judge"))
        self.assertEqual(sm.read_explore(self.slot, self.save_dir)["当前剧情"], "记下桥边风声。")

    def test_judge_trial_rolls_back_writes_before_failure_and_can_retry(self):
        self.existing_slot()
        before = self.active_files()
        go = self.run_command("go", 行为=[{"类型": "其他行为", "描述": "探看山道"}])
        self.assertNotIn("错误", go)
        self.assertNotIn("错误", self.plot())
        pending = self.pending_files()
        # Run the actual judge entrypoint in a fresh process, injecting an error only
        # after its trial writes a file. This tests the rollback path, not a precheck.
        code = (
            "import json; import engine; from store import save_manager as sm\n"
            "def fail_after_write(slot, payload):\n"
            "    data = sm.read_explore(slot)\n"
            "    data['当前剧情'] = '试算污染不得落盘'\n"
            "    sm.write_explore(slot, data)\n"
            "    return {'错误': '模拟下游 judge 错误', 'turn_state': 'AWAITING_JUDGE'}\n"
            "engine._legacy_judge = fail_after_write\n"
            "print(json.dumps(engine.judge(1, {'槽位': 1}), ensure_ascii=False))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
            env={**os.environ, "WUXIA_RPG_SAVE_DIR": self.save_dir,
                 "PYTHONPATH": str(SCRIPTS)},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        failed = json.loads(proc.stdout)
        self.assertIn("模拟下游 judge 错误", failed.get("错误", ""))
        self.assertEqual(self.pending_files(), pending)
        self.assertEqual(self.active_files(), before)
        self.assertTrue(ws.pending_exists(self.slot, self.save_dir))
        recovered = self.run_command("judge")
        self.assertNotIn("错误", recovered)
        self.assertEqual(sm.read_explore(self.slot, self.save_dir)["当前剧情"], "一阵风掠过竹林。")

    def test_reset_discards_pending_then_next_go_starts_fresh(self):
        self.existing_slot()
        before = self.active_files()
        go = self.run_command("go", 行为=[{"类型": "其他行为", "描述": "第一次巡查"}])
        self.assertNotIn("错误", go)
        self.assertNotIn("错误", self.plot(story="舍弃的稿子。"))
        blocked = self.run_command("go", 行为=[{"类型": "其他行为", "描述": "违规第二次"}])
        self.assertEqual(blocked.get("状态冲突"), "go_already_staged")
        self.assertEqual(blocked.get("turn_state"), turn_state.AWAITING_JUDGE)
        reset = self.run_command("turn-reset")
        self.assertEqual(reset.get("ok"), True, reset)
        self.assertEqual(reset.get("turn_state"), turn_state.READY)
        self.assertFalse(ws.pending_exists(self.slot, self.save_dir))
        self.assertEqual(self.active_files(), before)
        self.assertIsNone(ws.read_committed_response(self.slot, self.save_dir))
        self.assertNotIn("错误", self.run_command("go", 行为=[{"类型": "其他行为", "描述": "新的巡查"}]))
        self.assertNotIn("错误", self.plot(story="新的稿子。"))
        committed = self.run_command("judge")
        self.assertNotIn("错误", committed)
        self.assertEqual(sm.read_explore(self.slot, self.save_dir)["当前剧情"], "新的稿子。")

    def test_new_slot_is_invisible_before_opening_judge_and_reset_removes_it(self):
        created = self.run_command("go", 行为=[{"类型": "创建角色", "角色": character("新入江湖") }])
        self.assertNotIn("错误", created)
        self.assertEqual(created.get("turn_state"), turn_state.AWAITING_PLOT)
        self.assertTrue(ws.pending_exists(self.slot, self.save_dir))
        self.assertFalse(ws.active_exists(self.slot, self.save_dir))
        self.assertEqual(sm.list_slots(self.save_dir), [])
        bad = self.plot(story="少了开场背景。")
        self.assertIn("错误", bad)
        self.assertEqual(bad.get("turn_state"), turn_state.AWAITING_PLOT)
        self.assertFalse(ws.active_exists(self.slot, self.save_dir))
        valid = self.plot(story=OPENING_ERA_TEMPLATE + "\n\n新入江湖者上路。")
        self.assertNotIn("错误", valid)
        self.assertFalse(ws.active_exists(self.slot, self.save_dir))
        self.assertNotIn("错误", self.run_command("judge"))
        self.assertTrue(ws.active_exists(self.slot, self.save_dir))
        self.assertEqual([entry["slot"] for entry in sm.list_slots(self.save_dir)], [self.slot])
        self.assertFalse(ws.pending_exists(self.slot, self.save_dir))

        self.slot = 2
        another = self.run_command("go", 行为=[{"类型": "创建角色", "角色": character("取消建档") }])
        self.assertNotIn("错误", another)
        self.assertTrue(ws.pending_exists(self.slot, self.save_dir))
        self.assertEqual(self.run_command("turn-reset").get("ok"), True)
        self.assertFalse(Path(self.save_dir, "slot_2").exists())
        self.assertEqual([entry["slot"] for entry in sm.list_slots(self.save_dir)], [1])


if __name__ == "__main__":
    unittest.main()
