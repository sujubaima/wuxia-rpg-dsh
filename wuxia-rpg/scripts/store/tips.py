#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tips.json 交换文件——go/judge 进程间变更提示传递。

go 每次成功结算后覆盖写变更行；judge 每回合读（成功消费后清空，失败保留供重调）。
judge 失败 GM 必重调直至成功，无漏网残留。随 slot 存放，非长期存档（消费即清）。
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


def tips_path(slot):
    """go 结算变更提示的 slot 级交换文件：go 覆盖写，judge 读（成功后消费清空，失败保留供重调）。"""
    return os.path.join(sm.slot_path(slot), "tips.json")


def write_tips(slot, results):
    """go 每次成功结算后覆盖写 tips.json：有变更行则写入，无则跳过。

    results=[] 视为显式清空（judge 消费后调用）——直接删 tips.json；
    results 含变更行则覆盖写，供 judge 下一次消费。
    judge 失败 GM 必重调直至成功，无漏网残留。"""
    if not sm._slot_writable(slot):
        return
    lines = [r["变更"] for r in results if r.get("ok") and r.get("变更")]
    path = tips_path(slot)
    if not lines:
        # 显式清空（judge 消费后）：删文件，防重复拼入下一段 judge 的结算
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
        return
    try:
        atomic_write_json(path, lines)
    except OSError:
        pass


def read_tips(slot):
    """读取变更提示；不存在返回 []，损坏告警后降级。"""
    path = tips_path(slot)
    try:
        data = read_json(path, expected_type=list)
    except JsonMissingError:
        return []
    except JsonReadError as exc:
        warn_json_read(exc)
        return []
    return [str(x) for x in data]
