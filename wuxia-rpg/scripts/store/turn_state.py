#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已有正式存档的 go/judge 阶段状态。"""

import os

from common.json_io import JsonMissingError, JsonSchemaError, atomic_write_json, read_json
from store import save_manager as sm


VERSION = 1
READY = "READY"
AWAITING_JUDGE = "AWAITING_JUDGE"
AWAITING_BATTLE_START = "AWAITING_BATTLE_START"
VALID_STATES = {READY, AWAITING_JUDGE, AWAITING_BATTLE_START}
_RUNTIME_SUBDIR = ".runtime"
_FILENAME = "turn_state.json"


def _enabled(slot):
    try:
        return int(slot) > 0
    except (TypeError, ValueError):
        return False


def turn_state_path(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """返回 slot 内回合状态文件路径。"""
    return os.path.join(sm.slot_path(slot, save_dir), _RUNTIME_SUBDIR, _FILENAME)


def ready_state():
    """返回默认 READY 状态。"""
    return {
        "version": VERSION,
        "state": READY,
        "origin": None,
        "go_result": {},
    }


def _validate(path, data):
    if type(data.get("version")) is not int or data["version"] != VERSION:
        raise JsonSchemaError(path, f"version 应为整数 {VERSION}")
    state = data.get("state")
    if state not in VALID_STATES:
        raise JsonSchemaError(path, f"未知回合状态：{state!r}")
    origin = data.get("origin")
    if origin is not None and not isinstance(origin, str):
        raise JsonSchemaError(path, "origin 应为字符串或 null")
    go_result = data.get("go_result", {})
    if not isinstance(go_result, dict):
        raise JsonSchemaError(path, "go_result 应为对象")
    return {
        "version": VERSION,
        "state": state,
        "origin": origin,
        "go_result": go_result,
    }


def read_state(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """读取回合状态；正式 slot 缺失时视为 READY，slot<=0 始终绕过。"""
    if not _enabled(slot):
        return ready_state()
    path = turn_state_path(slot, save_dir)
    try:
        data = read_json(path, expected_type=dict)
    except JsonMissingError:
        return ready_state()
    return _validate(path, data)


def write_state(slot, state, *, origin=None, go_result=None,
                save_dir=sm.DEFAULT_SAVE_DIR):
    """原子写入正式 slot 的阶段状态；slot<=0 不落盘。"""
    if not _enabled(slot):
        return ready_state()
    data = {
        "version": VERSION,
        "state": state,
        "origin": origin,
        "go_result": {} if go_result is None else go_result,
    }
    path = turn_state_path(slot, save_dir)
    data = _validate(path, data)
    atomic_write_json(path, data, indent=2)
    return data


def reset_state(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """将正式 slot 重置为 READY；slot<=0 不落盘。"""
    return write_state(slot, READY, save_dir=save_dir)
