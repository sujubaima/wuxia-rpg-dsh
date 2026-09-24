#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回合剧情草稿，供 plot-writing 与最终 judge 交换。"""
import copy
import hashlib
import json
import os

from common.json_io import JsonMissingError, JsonSchemaError, atomic_write_json, read_json
from store import save_manager as sm


VERSION = 1
_FILENAME = "plot_draft.json"


def draft_path(slot):
    return os.path.join(sm.slot_path(slot), ".runtime", _FILENAME)


def _digest(payload):
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def read_draft(slot):
    path = draft_path(slot)
    try:
        data = read_json(path, expected_type=dict)
    except JsonMissingError:
        return None
    if (data.get("version") != VERSION or data.get("slot") != int(slot)
            or type(data.get("round")) is not int or data["round"] < 0
            or not isinstance(data.get("payload"), dict)
            or data.get("content_hash") != _digest(data["payload"])):
        raise JsonSchemaError(path, "剧情草稿内容损坏，请放弃本轮并重新开始")
    return copy.deepcopy(data)


def write_draft(slot, round_number, payload):
    if not sm._slot_writable(slot) or type(round_number) is not int or round_number < 0:
        raise ValueError("剧情草稿槽位或轮次无效")
    data = {
        "version": VERSION,
        "slot": int(slot),
        "round": round_number,
        "payload": copy.deepcopy(payload),
        "content_hash": _digest(payload),
    }
    atomic_write_json(draft_path(slot), data, indent=2)
    return copy.deepcopy(data)


def clear_draft(slot):
    try:
        os.remove(draft_path(slot))
    except FileNotFoundError:
        pass
