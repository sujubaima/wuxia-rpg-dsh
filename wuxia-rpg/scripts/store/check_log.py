#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check.json 交换文件——判定掷骰留痕，judge 按轮次核对提示带出。

check.py 每次掷骰追加一条记录（含轮次，轮次取自 save_manager.read_round，即 explore.json）；
engine.py judge 按当轮读取核对剧情是否带出判定提示。restore 读档时清空。
随 slot 存放，仅保留最近 5 轮，非长期存档。
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

CHECK_FILENAME = "check.json"


def check_log_path(slot):
    """判定留痕文件：check.py 每次掷骰追加一条记录，judge 按当前轮次读取核对。"""
    return os.path.join(sm.slot_path(slot), CHECK_FILENAME)


def trim_to_recent_rounds(records, keep=5):
    """保留涉及最近 keep 个不同轮次的记录，丢弃更早的。
    无轮次字段的记录（如调试残留）视为最新，保留。"""
    rounds = sorted({r.get("轮次") for r in records
                     if isinstance(r, dict) and isinstance(r.get("轮次"), (int, float))},
                    reverse=True)
    keep_set = set(rounds[:keep])
    return [r for r in records
            if not isinstance(r, dict)
            or not isinstance(r.get("轮次"), (int, float))
            or r.get("轮次") in keep_set]


def append_check(slot, record):
    """追加判定留痕；旧文件损坏时告警并从空列表重建，写入失败不影响判定。"""
    if not sm._slot_writable(slot):
        return
    path = check_log_path(slot)
    try:
        data = read_json(path, expected_type=list)
    except JsonMissingError:
        data = []
    except JsonReadError as exc:
        warn_json_read(exc)
        data = []
    data.append(record)
    data = trim_to_recent_rounds(data, keep=5)
    try:
        atomic_write_json(path, data, indent=2)
    except OSError:
        pass


def missing_check_hints(slot, plot):
    """核对当轮判定提示；文件缺失返回空，损坏告警后降级。"""
    if not plot:
        return []
    rnd = sm.read_round(slot)
    try:
        logs = read_json(check_log_path(slot), expected_type=list)
    except JsonMissingError:
        return []
    except JsonReadError as exc:
        warn_json_read(exc)
        return []
    text = str(plot)
    missing = []
    for rec in reversed(logs):
        if not isinstance(rec, dict):
            continue
        r = rec.get("轮次")
        if r != rnd:
            # 追加顺序保证轮次单调不减：遇到更早轮次即无当轮记录可读
            if isinstance(r, (int, float)) and r < rnd:
                break
            continue
        hint = rec.get("提示") or ""
        # 须以反引号高亮形态嵌入剧情：缺失（含未包裹反引号）即视为未带出
        if hint and f"`{hint}`" not in text:
            missing.append(f"`{hint}`")
    return missing
