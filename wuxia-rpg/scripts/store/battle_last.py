#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""battle_last.json 交换文件——战斗操控 go 的结算底稿。

go 覆盖写（战报/回合详情/战局状态/玩家界面/战果/经验结算），judge 战斗-推进 读入打包 battle-ui，
战后处置 judge 结束战斗后清理。随 slot 存放，非长期存档（战后清）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from common.json_io import (
    JsonMissingError,
    JsonReadError,
    atomic_write_json,
    read_json,
    warn_json_read,
)
from store import save_manager as sm

_BATTLE_LAST_FILENAME = "battle_last.json"


def battle_last_path(slot):
    """战斗操控 go 的结算底稿路径：go 覆盖写，judge 战斗-推进 读入打包 battle-ui。战后处置清理。"""
    return os.path.join(sm.slot_path(slot), _BATTLE_LAST_FILENAME)


def write_battle_last(slot, bt_data):
    """战斗 go 结算成功即覆盖写 battle_last.json（剔除界面字段与 go 级附键）。"""
    if not sm._slot_writable(slot):
        return
    keep = {k: v for k, v in bt_data.items()
            if k not in ("界面", "saved", "剩余", "结算", "剧情描写", "场景要素")}
    try:
        atomic_write_json(battle_last_path(slot), keep)
    except OSError:
        pass


def read_battle_last(slot):
    """读 battle_last.json；不存在返回 None，损坏告警后降级。"""
    path = battle_last_path(slot)
    try:
        return read_json(path, expected_type=dict)
    except JsonMissingError:
        return None
    except JsonReadError as exc:
        warn_json_read(exc)
        return None
