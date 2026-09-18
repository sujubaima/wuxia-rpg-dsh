#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""即兴任务蓝图草稿——prepare/judge 间的短期、非权威交换文件。"""
import copy
import hashlib
import json
import os

from common.json_io import JsonMissingError, JsonSchemaError, atomic_write_json, read_json
from store import save_manager as sm


VERSION = 3
_RUNTIME_SUBDIR = ".runtime"
_FILENAME = "quest_drafts.json"
_KINDS = {"create", "extend", "modify"}


def quest_drafts_path(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    return os.path.join(sm.slot_path(slot, save_dir), _RUNTIME_SUBDIR, _FILENAME)


def definition_hash(kind, definition, hidden=False):
    """按规范任务定义生成稳定内容摘要；创建草稿同时纳入隐藏语义。"""
    if kind not in _KINDS:
        raise ValueError(f"未知任务草稿类型【{kind}】")
    canonical = {
        "kind": kind,
        "definition": definition,
    }
    if kind == "create":
        canonical["hidden"] = bool(hidden)
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty(slot):
    return {"version": VERSION, "slot": int(slot), "round": None, "order": [], "drafts": {}}


def _validate_record(path, key, raw):
    if not isinstance(raw, dict):
        raise JsonSchemaError(path, f"草稿【{key}】须为对象")
    required = {
        "quest_name", "kind", "payload", "hidden", "content_hash",
        "definition_version", "summary",
    }
    missing = required - set(raw)
    if missing:
        raise JsonSchemaError(path, f"草稿【{key}】缺少字段：{sorted(missing)}")
    if set(raw) - required:
        raise JsonSchemaError(path, f"草稿【{key}】含非预期字段：{sorted(set(raw) - required)}")
    if raw.get("quest_name") != key:
        raise JsonSchemaError(path, f"草稿键【{key}】与 quest_name 不一致")
    if raw.get("kind") not in _KINDS:
        raise JsonSchemaError(path, f"草稿【{key}】kind 不合法")
    if not isinstance(raw.get("payload"), dict):
        raise JsonSchemaError(path, f"草稿【{key}】payload 须为对象")
    if not isinstance(raw.get("hidden"), bool):
        raise JsonSchemaError(path, f"草稿【{key}】hidden 须为布尔值")
    if raw["kind"] in ("extend", "modify") and raw["hidden"]:
        raise JsonSchemaError(path, f"草稿【{key}】hidden 必须为 false")
    content_hash = raw.get("content_hash")
    if (not isinstance(content_hash, str) or len(content_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in content_hash)):
        raise JsonSchemaError(path, f"草稿【{key}】content_hash 无效")
    if type(raw.get("definition_version")) is not int:
        raise JsonSchemaError(path, f"草稿【{key}】definition_version 须为整数")
    if not isinstance(raw.get("summary"), dict):
        raise JsonSchemaError(path, f"草稿【{key}】summary 须为对象")
    return copy.deepcopy(raw)


def read_drafts(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """读取当前草稿批次；不存在视为空，损坏文件不得降级采用。"""
    path = quest_drafts_path(slot, save_dir)
    try:
        data = read_json(path, expected_type=dict)
    except JsonMissingError:
        return _empty(slot)
    required = {"version", "slot", "round", "order", "drafts"}
    missing = required - set(data)
    if missing:
        raise JsonSchemaError(path, f"草稿文件缺少字段：{sorted(missing)}")
    if set(data) - required:
        raise JsonSchemaError(path, f"草稿文件含非预期字段：{sorted(set(data) - required)}")
    if type(data.get("version")) is not int or data["version"] != VERSION:
        raise JsonSchemaError(path, f"version 应为整数 {VERSION}，请重新执行 quest-prepare")
    if type(data.get("slot")) is not int or data["slot"] <= 0:
        raise JsonSchemaError(path, "slot 须为正整数")
    if data["slot"] != int(slot):
        raise JsonSchemaError(path, "草稿文件槽位与目标槽位不一致")
    if type(data.get("round")) is not int or data["round"] < 0:
        raise JsonSchemaError(path, "round 须为非负整数")
    order = data.get("order")
    if (not isinstance(order, list) or any(not isinstance(item, str) or not item for item in order)
            or len(order) != len(set(order))):
        raise JsonSchemaError(path, "order 须为无重复非空线索名称数组")
    drafts = data.get("drafts")
    if not isinstance(drafts, dict):
        raise JsonSchemaError(path, "drafts 须为对象")
    if set(order) != set(drafts):
        raise JsonSchemaError(path, "order 与 drafts 任务集合不一致")
    return {
        "version": VERSION,
        "slot": data["slot"],
        "round": data["round"],
        "order": list(order),
        "drafts": {
            key: _validate_record(path, key, value)
            for key, value in drafts.items()
        },
    }


def write_batch(slot, round_number, records, save_dir=sm.DEFAULT_SAVE_DIR):
    """以最新成功批次完整替换当前草稿文件。"""
    if not sm._slot_writable(slot):
        raise ValueError("任务草稿槽位须为正整数")
    if type(round_number) is not int or round_number < 0:
        raise ValueError("任务草稿 round 须为非负整数")
    if not isinstance(records, list) or not records:
        raise ValueError("任务草稿批次须为非空数组")
    path = quest_drafts_path(slot, save_dir)
    order = []
    drafts = {}
    for record in records:
        quest_name = record.get("quest_name") if isinstance(record, dict) else None
        if not isinstance(quest_name, str) or not quest_name:
            raise ValueError("任务草稿缺少 quest_name")
        if quest_name in drafts:
            raise ValueError(f"任务草稿批次含重复线索名称【{quest_name}】")
        drafts[quest_name] = _validate_record(path, quest_name, record)
        order.append(quest_name)
    data = {
        "version": VERSION,
        "slot": int(slot),
        "round": round_number,
        "order": order,
        "drafts": drafts,
    }
    atomic_write_json(path, data, indent=2)
    return copy.deepcopy(data)


def select_drafts(slot, quest_names, save_dir=sm.DEFAULT_SAVE_DIR):
    """按当前批次顺序返回指定任务草稿，并在返回前确认全部存在。"""
    if (not isinstance(quest_names, list) or not quest_names
            or any(not isinstance(item, str) or not item for item in quest_names)):
        raise ValueError("线索-采用草稿须传入非空 名称列表")
    if len(quest_names) != len(set(quest_names)):
        raise ValueError("线索-采用草稿的 名称列表 不得重复")
    data = read_drafts(slot, save_dir)
    missing = [quest_name for quest_name in quest_names if quest_name not in data["drafts"]]
    if missing:
        raise ValueError(f"任务草稿不存在【{'、'.join(missing)}】")
    selected = set(quest_names)
    return {
        "slot": data["slot"],
        "round": data["round"],
        "records": [
            copy.deepcopy(data["drafts"][quest_name])
            for quest_name in data["order"]
            if quest_name in selected
        ],
    }


def clear_round(slot, round_number, save_dir=sm.DEFAULT_SAVE_DIR):
    data = read_drafts(slot, save_dir)
    if data["round"] == round_number:
        clear_all(slot, save_dir)


def clear_all(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    try:
        os.remove(quest_drafts_path(slot, save_dir))
    except FileNotFoundError:
        pass
