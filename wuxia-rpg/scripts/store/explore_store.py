#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""explore.json 字段读写的收敛入口。

explore.json 是 slot 级实时状态镜像（GM 维护字段），字段集见 save_manager.EXPLORE_KEYS：
经历概括 / 任务摘要及进度 / 队伍 / 状态提示 / 当前位置 / 当前时间 / 体力 / 当前剧情 / 场景要素，
外加独立持久字段 round。

本模块把散落于 engine/scene/event 等处的 explore["字段"] 直访收敛为统一接口，
内部仍走 save_manager.read_explore / write_explore，完整保留其语义：
  - 体力 写入前夹取 [0, STAMINA_MAX]
  - 当前位置/当前时间/队伍 未传则保留现值
  - 任务摘要及进度 按「名称」增量合并
  - 经历概括/当前剧情/场景要素 每回合直接落盘（实时与存档路径一致写入）
  - round 透传保留

读写一律走 save_manager 的默认存档目录（DEFAULT_SAVE_DIR），不暴露 save_dir 参数，
以保证读与写路径一致。接口：
  get(slot, field, default=None)              读单字段
  get_all(slot)                                读整个 explore dict
  set(slot, field, value, *, narrative=False) 写单字段
  update(slot, mapping, *, narrative=False)    批量写多字段
  unset(slot, field, *, narrative=False)       删字段
  get_round(slot) / set_round(slot, n)         round 读写（独立持久字段）
  upsert_event(slot, event)                    追加/替换单条事件（任务摘要及进度，按名称合并）
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from store import save_manager as sm

# 实时回合保留现值的字段（现为空，所有字段每回合直接落盘）
NARRATIVE_KEYS = set(sm.NARRATIVE_PRESERVE_KEYS)


def get(slot, field, default=None):
    """读单字段；explore.json 不存在或缺字段返回 default。"""
    return (sm.read_explore(slot) or {}).get(field, default)


def get_all(slot):
    """读整个 explore dict（等价 read_explore）；不存在返回 {}。"""
    return sm.read_explore(slot) or {}


def _write(slot, explore, narrative):
    """据 narrative 选择 write_explore 的 preserve_narrative：实时回合 True / 存档覆盖 False。"""
    sm.write_explore(slot, explore, preserve_narrative=not narrative)


def set(slot, field, value, *, narrative=False):
    """写单字段。

    存档定稿字段（经历概括）在实时回合（narrative=False）下会被 write_explore 保留现值而写不进——
    此情形显式抛错，避免静默吞写；需写经历概括须传 narrative=True（存档覆盖路径）。
    """
    explore = sm.read_explore(slot) or {}
    if field in NARRATIVE_KEYS and not narrative:
        raise ValueError(f"字段【{field}】为存档定稿内容，实时回合不可写；须走存档路径 set(..., narrative=True)")
    explore[field] = value
    _write(slot, explore, narrative)


def update(slot, mapping, *, narrative=False):
    """批量写多字段。mapping: dict。存档定稿字段在 narrative=False 时同 set 抛错。"""
    if not isinstance(mapping, dict):
        raise TypeError("update 的 mapping 须为 dict")
    blocked = [k for k in mapping if k in NARRATIVE_KEYS and not narrative]
    if blocked:
        raise ValueError(f"字段【{','.join(blocked)}】为存档定稿内容，实时回合不可写；须走存档路径 update(..., narrative=True)")
    explore = sm.read_explore(slot) or {}
    explore.update(mapping)
    _write(slot, explore, narrative)


def unset(slot, field, *, narrative=False):
    """删字段。存档定稿字段实时回合删除无意义（写时会被现值覆盖回填），同样要求 narrative=True。"""
    if field in NARRATIVE_KEYS and not narrative:
        raise ValueError(f"字段【{field}】为存档定稿内容，实时回合不可删；须走存档路径 unset(..., narrative=True)")
    explore = sm.read_explore(slot) or {}
    explore.pop(field, None)
    _write(slot, explore, narrative)


def upsert_event(slot, event):
    """追加或替换单条事件（任务摘要及进度）。按 event「名称」合并：匹配则整体替换，否则新增。
    复用 write_explore 的按名称增量合并；传入单条事件列表即可。"""
    if not isinstance(event, dict) or not event.get("名称"):
        raise ValueError("upsert_event 须传含「名称」字段的事件 dict")
    explore = sm.read_explore(slot) or {}
    events = list(explore.get("任务摘要及进度") or [])
    name = event["名称"]
    events = [event if e.get("名称") == name else e for e in events]
    if not any(e.get("名称") == name for e in events):
        events.append(event)
    explore["任务摘要及进度"] = events
    _write(slot, explore, narrative=False)


def get_round(slot):
    """读 round（独立持久字段，总交互轮次）。"""
    return sm.read_round(slot)


def set_round(slot, n):
    """写 round。"""
    sm.write_round(slot, n)
