#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""显式建档槽位、冲突返回与 claim 状态迁移。"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import dao as dq  # noqa: E402
from store import save_manager as sm  # noqa: E402
from store import turn_state  # noqa: E402
from world import scene as sc  # noqa: E402

ENGINE = SCRIPTS / "engine.py"

_BATTLE_JUDGE_ACTIONS = {"战斗-开始", "战斗-触发", "战斗-推进"}


def judge_elements(save_dir, slot, changes=None):
    """按 judge 落定后位置构造最小合法场景要素：优先取行为中玩家「抵达」目的地；
    功能场景须含绑定功能NPC与全套特殊指令。"""
    position = None
    for action in changes or []:
        if isinstance(action, dict) and action.get("类型") == "抵达" and not action.get("角色"):
            position = action.get("位置") or action.get("目的地")
    if not position:
        position = (sm.read_explore(slot, save_dir) or {}).get("当前位置") or ""
    region, _, scene = position.partition("·")
    stype = sc.scene_type(slot, region, scene)
    npc = sc.scene_npc(slot, region, scene)
    commands = {"驿站": ["远行（舟车）"], "店铺": ["购买", "出售"], "客栈": ["投宿"]}.get(stype)
    if npc and commands:
        return [{"主体": npc, "描写": "当值",
                 "特殊指令": [{"名称": c, "可用": True} for c in commands]}]
    return [{"主体": "四周", "描写": "一切如常"}]


def character(name):
    return {
        "名称": name,
        "阵营": "江湖",
        "性别": "男",
        "年龄": 20,
        "武功定位": "武者",
        "一级属性": {"根骨": 10, "力道": 10, "身法": 10, "内功": 10},
        "极性": {"内功": "中", "力道": "中", "身法": "中", "根骨": "中"},
        "铜钱": 1000,
        "物品": ["玉佩"],
        "武学": [{"名称": "百缠手", "等级": 1}],
        "武艺": {"搏击": 10, "剑法": 0, "刀法": 0, "长兵": 0, "奇门": 0, "暗器": 0},
        "技艺": {"音律": 0, "弈棋": 0, "诗书": 0, "绘画": 0, "医术": 0, "博物": 0},
        "装备": {},
        "人设": "测试角色",
    }


def run_engine(save_dir, slot, actions, command="go", **extra):
    payload = {"槽位": slot, "行为": actions, **extra}
    if command == "judge":
        payload.setdefault("提及地点", [])
        # 场景要素为非战斗 judge 必填：骨架按落定位置自动补全（显式传入时不覆盖）
        battle = any(isinstance(a, dict) and a.get("类型") in _BATTLE_JUDGE_ACTIONS
                     for a in actions or [])
        if "场景要素" not in payload and not battle:
            payload["场景要素"] = judge_elements(save_dir, slot, actions)
    env = {**os.environ, "WUXIA_RPG_SAVE_DIR": save_dir}
    proc = subprocess.run(
        [sys.executable, str(ENGINE), command],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"engine 输出不是 JSON: {proc.stdout[:300]}\n{proc.stderr[-300:]}") from exc
    if proc.returncode not in (0, 2):
        raise AssertionError(f"engine 异常退出 {proc.returncode}: {proc.stderr[-500:]}")
    return result


def directory_snapshot(root):
    root = Path(root)
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class SlotAllocationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save_dir = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def test_title_returns_next_slot_and_create_uses_exact_requested_slot(self):
        title = run_engine(self.save_dir, 0, [{"类型": "开始游戏"}])
        self.assertEqual(title.get("next_slot"), 1)
        self.assertFalse(Path(self.save_dir, "slot_0").exists())

        created = run_engine(
            self.save_dir,
            5,
            [{"类型": "创建角色", "角色": character("越五峰")}],
        )
        settlement = (created.get("结算") or [{}])[0]
        self.assertIsNone(created.get("错误"), created)
        self.assertEqual(created.get("槽位"), 5)
        self.assertEqual(settlement.get("新建slot"), 5)
        self.assertEqual(created.get("turn_state"), turn_state.AWAITING_JUDGE)
        self.assertTrue(Path(self.save_dir, "slot_5").is_dir())
        self.assertFalse(Path(self.save_dir, "slot_1").exists())
        quests = sm.read_quest_state(5, self.save_dir)
        facts = sm.read_world_facts(5, self.save_dir)
        self.assertEqual(len(quests.get("definitions", {})), 19)
        self.assertTrue(all(
            runtime.get("lifecycle") == "hidden"
            for runtime in quests.get("runtimes", {}).values()
        ))
        self.assertIn("player.region@world", facts.get("records", {}))
        self.assertEqual((sm.read_explore(5, self.save_dir) or {}).get("任务摘要及进度"), [])

        refreshed = run_engine(self.save_dir, 0, [{"类型": "开始游戏"}])
        self.assertEqual(refreshed.get("next_slot"), 6)

    def test_invalid_and_occupied_slots_return_latest_candidate_without_writes(self):
        created = run_engine(
            self.save_dir,
            5,
            [{"类型": "创建角色", "角色": character("守槽人")}],
        )
        self.assertEqual(created.get("turn_state"), turn_state.AWAITING_JUDGE)
        slot_root = Path(self.save_dir, "slot_5")
        before = directory_snapshot(slot_root)

        invalid = run_engine(
            self.save_dir,
            0,
            [{"类型": "创建角色", "角色": character("零号客")}],
        )
        self.assertEqual(invalid.get("错误码"), "create_slot_required")
        self.assertEqual(invalid.get("next_slot"), 6)
        invalid_message = invalid.get("错误") or invalid.get("渲染文本") or ""
        self.assertIn("6", str(invalid_message))
        self.assertFalse(Path(self.save_dir, "slot_0").exists())

        conflict = run_engine(
            self.save_dir,
            5,
            [{"类型": "创建角色", "角色": character("后来客")}],
        )
        self.assertEqual(conflict.get("错误码"), "slot_occupied")
        self.assertEqual(conflict.get("next_slot"), 6)
        self.assertNotEqual(conflict.get("状态冲突"), "go_already_committed")
        conflict_message = conflict.get("错误") or conflict.get("渲染文本") or ""
        self.assertIn("6", str(conflict_message))
        self.assertEqual(directory_snapshot(slot_root), before)

    def test_mixed_claim_is_rejected_and_conflict_retry_gets_one_starter_pack(self):
        run_engine(
            self.save_dir,
            2,
            [{"类型": "创建角色", "角色": character("先来者")}],
        )
        conflict = run_engine(
            self.save_dir,
            2,
            [{"类型": "创建角色", "角色": character("重试者")}],
        )
        retry_slot = conflict.get("next_slot")
        self.assertEqual(retry_slot, 3)

        mixed = run_engine(
            self.save_dir,
            retry_slot,
            [
                {"类型": "创建角色", "角色": character("混合客")},
                {"类型": "开始游戏"},
            ],
        )
        mixed_message = mixed.get("错误") or mixed.get("渲染文本") or ""
        self.assertIn("唯一 action", str(mixed_message))
        self.assertFalse(Path(self.save_dir, f"slot_{retry_slot}").exists())

        retried = run_engine(
            self.save_dir,
            retry_slot,
            [{"类型": "创建角色", "角色": character("重试者")}],
        )
        self.assertIsNone(retried.get("错误"), retried)
        self.assertEqual(retried.get("槽位"), retry_slot)
        self.assertEqual(retried.get("turn_state"), turn_state.AWAITING_JUDGE)

        saved = dq.read_character_file(
            "重试者",
            data_dir=sm.slot_data_dir(retry_slot, self.save_dir),
        )
        self.assertIsNotNone(saved)
        self.assertEqual(saved.get("铜钱"), 1500)
        items = saved.get("物品") or []
        names = [item if isinstance(item, str) else item.get("名称") for item in items]
        self.assertEqual(names.count("小还丹"), 2)
        self.assertEqual(names.count("补气丸"), 2)

        from engine import OPENING_ERA_TEMPLATE

        opened = run_engine(
            self.save_dir,
            retry_slot,
            [],
            command="judge",
            当前剧情=OPENING_ERA_TEMPLATE + "\n\n重试者踏入江湖。",
        )
        self.assertIsNone(opened.get("错误"), opened)
        self.assertEqual(opened.get("turn_state"), turn_state.READY)

    def test_opening_judge_without_narrative_is_rejected_until_rewritten(self):
        created = run_engine(
            self.save_dir,
            1,
            [{"类型": "创建角色", "角色": character("开卷人")}],
        )
        self.assertEqual(created.get("turn_state"), turn_state.AWAITING_JUDGE)
        slot_root = Path(self.save_dir, "slot_1")
        before = directory_snapshot(slot_root)

        from engine import OPENING_ERA_TEMPLATE

        bad_narratives = (
            {}, {"当前剧情": ""}, {"当前剧情": "   "},
            {"当前剧情": "开卷人负剑出蜀，初入江湖。"},
        )
        for bad_payload in bad_narratives:
            rejected = run_engine(
                self.save_dir, 1, [], command="judge", **bad_payload
            )
            message = str(rejected.get("错误") or "")
            self.assertIn("开场白", message, rejected)
            self.assertIn("大明万历年间", message, rejected)
            self.assertEqual(rejected.get("turn_state"), turn_state.AWAITING_JUDGE)
            self.assertEqual(directory_snapshot(slot_root), before)

        opening_plot = (
            OPENING_ERA_TEMPLATE + "\n\n开卷人负剑出蜀，初入江湖。"
        )
        accepted = run_engine(
            self.save_dir,
            1,
            [],
            command="judge",
            当前剧情=opening_plot,
        )
        self.assertIsNone(accepted.get("错误"), accepted)
        self.assertEqual(accepted.get("turn_state"), turn_state.READY)
        self.assertEqual(
            (sm.read_explore(1, self.save_dir) or {}).get("当前剧情"),
            opening_plot,
        )

        from engine import OPENING_ERA_SENTENCE

        sentence_only = run_engine(
            self.save_dir,
            2,
            [{"类型": "创建角色", "角色": character("短句客")}],
        )
        self.assertEqual(sentence_only.get("turn_state"), turn_state.AWAITING_JUDGE)
        brief = run_engine(
            self.save_dir,
            2,
            [],
            command="judge",
            当前剧情=OPENING_ERA_SENTENCE + "\n\n短句客踏入江湖。",
        )
        self.assertIsNone(brief.get("错误"), brief)
        self.assertEqual(brief.get("turn_state"), turn_state.READY)

    def test_atomic_reservation_allows_only_one_concurrent_creator(self):
        env = {**os.environ, "WUXIA_RPG_SAVE_DIR": self.save_dir}
        processes = []
        for name in ("并发甲", "并发乙"):
            payload = {
                "槽位": 4,
                "行为": [{"类型": "创建角色", "角色": character(name)}],
            }
            processes.append(subprocess.Popen(
                [sys.executable, str(ENGINE), "go"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            ))
            processes[-1].stdin.write(json.dumps(payload, ensure_ascii=False))
            processes[-1].stdin.close()

        responses = []
        for proc in processes:
            stdout = proc.stdout.read()
            stderr = proc.stderr.read()
            proc.stdout.close()
            proc.stderr.close()
            proc.wait(timeout=60)
            self.assertIn(proc.returncode, (0, 2), stderr)
            responses.append(json.loads(stdout))

        successes = [
            res for res in responses
            if (res.get("结算") or [{}])[0].get("ok") is True
        ]
        conflicts = [res for res in responses if res.get("错误码") == "slot_occupied"]
        self.assertEqual(len(successes), 1, responses)
        self.assertEqual(len(conflicts), 1, responses)
        self.assertEqual(conflicts[0].get("next_slot"), 5)
        self.assertTrue(Path(self.save_dir, "slot_4").is_dir())

    def test_deleting_highest_slot_refreshes_next_slot(self):
        from engine import OPENING_ERA_TEMPLATE

        for slot, name in ((2, "低槽位"), (7, "高槽位")):
            created = run_engine(
                self.save_dir,
                slot,
                [{"类型": "创建角色", "角色": character(name)}],
            )
            self.assertIsNone(created.get("错误"), created)
            opened = run_engine(
                self.save_dir,
                slot,
                [],
                command="judge",
                当前剧情=OPENING_ERA_TEMPLATE + f"\n\n{name}初入江湖。",
            )
            self.assertIsNone(opened.get("错误"), opened)

        self.assertEqual(
            run_engine(self.save_dir, 0, [{"类型": "开始游戏"}]).get("next_slot"),
            8,
        )
        deleted = run_engine(self.save_dir, 7, [{"类型": "删除存档"}])
        self.assertTrue((deleted.get("结算") or [{}])[0].get("ok"), deleted)
        self.assertFalse(Path(self.save_dir, "slot_7").exists())
        self.assertEqual(
            run_engine(self.save_dir, 0, [{"类型": "开始游戏"}]).get("next_slot"),
            3,
        )

    def test_delete_bypasses_pending_turn_state(self):
        from store import turn_state

        # 删除存档是存档管理操作：slot 卡在 AWAITING_JUDGE / AWAITING_BATTLE_START 时也须放行
        for slot, pending in (
            (3, turn_state.AWAITING_JUDGE),
            (4, turn_state.AWAITING_BATTLE_START),
        ):
            created = run_engine(
                self.save_dir,
                slot,
                [{"类型": "创建角色", "角色": character("卡状态者")}],
            )
            self.assertIsNone(created.get("错误"), created)
            turn_state.write_state(
                slot, pending, origin="测试", save_dir=self.save_dir,
            )
            deleted = run_engine(self.save_dir, slot, [{"类型": "删除存档"}])
            self.assertTrue((deleted.get("结算") or [{}])[0].get("ok"), deleted)
            self.assertFalse(Path(self.save_dir, f"slot_{slot}").exists())

    def test_save_manager_cleans_partial_slot_and_does_not_mutate_conflict_payload(self):
        first = character("直接甲")
        sm.create_slot(first, 2, save_dir=self.save_dir)
        direct_quests = sm.read_quest_state(2, self.save_dir)
        self.assertEqual(len(direct_quests.get("definitions", {})), 19)
        self.assertTrue(all(
            runtime.get("lifecycle") == "hidden"
            for runtime in direct_quests.get("runtimes", {}).values()
        ))

        second = character("直接乙")
        original = copy.deepcopy(second)
        with self.assertRaises(sm.SlotOccupiedError) as caught:
            sm.create_slot(second, 2, save_dir=self.save_dir)
        self.assertEqual(caught.exception.next_slot, 3)
        self.assertEqual(second, original)

        with mock.patch.object(sm, "write_meta", side_effect=RuntimeError("故障注入")):
            with self.assertRaisesRegex(RuntimeError, "故障注入"):
                sm.create_slot(character("半成品"), 3, save_dir=self.save_dir)
        self.assertFalse(Path(self.save_dir, "slot_3").exists())

        with tempfile.TemporaryDirectory() as bad_data:
            quest_dir = Path(bad_data, "quests")
            quest_dir.mkdir()
            Path(quest_dir, "损坏预设.json").write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "损坏预设.json"):
                sm.create_slot(
                    character("坏预设"), 4,
                    save_dir=self.save_dir, data_dir=bad_data,
                )
        self.assertFalse(Path(self.save_dir, "slot_4").exists())


if __name__ == "__main__":
    unittest.main()
