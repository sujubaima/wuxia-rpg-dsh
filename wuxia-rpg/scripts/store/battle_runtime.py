#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战斗运行时文件路径与清理。"""

import os
import tempfile

from common import dao as dq

STATE_FILENAME = "battle_state.json"
META_FILENAME = "battle_meta.json"
REPORT_FILENAME = "battle_report.json"
FILENAMES = (STATE_FILENAME, META_FILENAME, REPORT_FILENAME)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_DIR = os.path.join(HERE, "tmp")


def runtime_dir(slot=None):
    """返回战斗运行时目录；正式游戏按 slot 隔离，无 slot 时使用临时目录。"""
    if slot is not None:
        return os.path.join(dq.slot_path(slot), ".runtime", "battle")
    root = os.environ.get("WUXIA_RPG_RUNTIME_DIR")
    if not root:
        root = os.path.join(tempfile.gettempdir(), "wuxia-rpg-runtime")
    return os.path.join(root, "battle")


def file_path(filename, slot=None):
    return os.path.join(runtime_dir(slot), filename)


def state_path(slot=None):
    return file_path(STATE_FILENAME, slot)


def meta_path(slot=None):
    return file_path(META_FILENAME, slot)


def report_path(slot=None):
    return file_path(REPORT_FILENAME, slot)


def legacy_path(filename, slot=None):
    root, ext = os.path.splitext(filename)
    suffix = f"_slot{int(slot)}" if slot is not None else ""
    return os.path.join(LEGACY_DIR, f"{root}{suffix}{ext}")


def read_path(filename, slot=None):
    """优先返回新路径；不存在时回退升级前 scripts/tmp 中的同槽位文件。"""
    current = file_path(filename, slot)
    if os.path.isfile(current):
        return current
    legacy = legacy_path(filename, slot)
    return legacy if os.path.isfile(legacy) else current


def battle_exists(slot=None):
    return os.path.isfile(read_path(STATE_FILENAME, slot))


def clear(slot=None):
    """清理指定战斗的新旧运行时文件，不触碰 slot 的其他状态。"""
    for filename in FILENAMES:
        for path in (file_path(filename, slot), legacy_path(filename, slot)):
            try:
                os.remove(path)
            except OSError:
                pass
    directory = runtime_dir(slot)
    try:
        os.rmdir(directory)
    except OSError:
        return
    if slot is not None:
        try:
            os.rmdir(os.path.dirname(directory))
        except OSError:
            pass
