#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景规划草稿——scene-prepare/judge 间的短期、非权威交换文件。"""
import copy
import hashlib
import json
import os

from common.json_io import JsonMissingError, JsonSchemaError, atomic_write_json, read_json
from store import save_manager as sm


VERSION = 1
_RUNTIME_SUBDIR = ".runtime"
_FILENAME = "scene_drafts.json"
_KINDS = {"登记场景", "隔离地点"}


def scene_drafts_path(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    return os.path.join(sm.slot_path(slot, save_dir), _RUNTIME_SUBDIR, _FILENAME)


def operations_hash(operations):
    encoded = json.dumps(
        operations, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty(slot):
    return {
        "version": VERSION,
        "slot": int(slot),
        "round": None,
        "operations": [],
        "content_hash": "",
    }


def _validate_operations(path, operations):
    if not isinstance(operations, list) or not operations:
        raise JsonSchemaError(path, "operations 须为非空数组")
    out = []
    for index, operation in enumerate(operations, 1):
        if not isinstance(operation, dict):
            raise JsonSchemaError(path, f"第 {index} 项场景操作须为对象")
        if operation.get("类型") not in _KINDS:
            raise JsonSchemaError(path, f"第 {index} 项场景操作类型不合法")
        out.append(copy.deepcopy(operation))
    return out


def read_draft(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """读取当前场景草稿；不存在视为空，损坏文件不得降级采用。"""
    path = scene_drafts_path(slot, save_dir)
    try:
        data = read_json(path, expected_type=dict)
    except JsonMissingError:
        return _empty(slot)
    required = {"version", "slot", "round", "operations", "content_hash"}
    missing = required - set(data)
    if missing:
        raise JsonSchemaError(path, f"场景草稿文件缺少字段：{sorted(missing)}")
    if set(data) - required:
        raise JsonSchemaError(path, f"场景草稿文件含非预期字段：{sorted(set(data) - required)}")
    if type(data.get("version")) is not int or data["version"] != VERSION:
        raise JsonSchemaError(path, f"version 应为整数 {VERSION}，请重新执行 scene-prepare")
    if type(data.get("slot")) is not int or data["slot"] <= 0:
        raise JsonSchemaError(path, "slot 须为正整数")
    if data["slot"] != int(slot):
        raise JsonSchemaError(path, "场景草稿文件槽位与目标槽位不一致")
    if type(data.get("round")) is not int or data["round"] < 0:
        raise JsonSchemaError(path, "round 须为非负整数")
    operations = _validate_operations(path, data.get("operations"))
    content_hash = data.get("content_hash")
    if (not isinstance(content_hash, str) or len(content_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in content_hash)):
        raise JsonSchemaError(path, "content_hash 无效")
    if operations_hash(operations) != content_hash:
        raise JsonSchemaError(path, "场景草稿内容摘要不匹配，请重新执行 scene-prepare")
    return {
        "version": VERSION,
        "slot": data["slot"],
        "round": data["round"],
        "operations": operations,
        "content_hash": content_hash,
    }


def write_batch(slot, round_number, operations, save_dir=sm.DEFAULT_SAVE_DIR):
    """以最新成功批次完整替换当前场景草稿。空批次明确清除草稿。"""
    if not sm._slot_writable(slot):
        raise ValueError("场景草稿槽位须为正整数")
    if type(round_number) is not int or round_number < 0:
        raise ValueError("场景草稿 round 须为非负整数")
    if not isinstance(operations, list):
        raise ValueError("场景草稿批次须为数组")
    if not operations:
        clear_all(slot, save_dir)
        return _empty(slot)
    path = scene_drafts_path(slot, save_dir)
    normalized = _validate_operations(path, operations)
    data = {
        "version": VERSION,
        "slot": int(slot),
        "round": round_number,
        "operations": normalized,
        "content_hash": operations_hash(normalized),
    }
    atomic_write_json(path, data, indent=2)
    return copy.deepcopy(data)


def select_draft(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    data = read_draft(slot, save_dir)
    if not data["operations"]:
        raise ValueError("本轮没有可采用的场景草稿")
    return data


def clear_round(slot, round_number, save_dir=sm.DEFAULT_SAVE_DIR):
    data = read_draft(slot, save_dir)
    if data["round"] == round_number:
        clear_all(slot, save_dir)


def clear_all(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    try:
        os.remove(scene_drafts_path(slot, save_dir))
    except FileNotFoundError:
        pass
