#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事件数据层——explore.json「任务摘要及进度」字段的取数入口。

从 event.py 下沉：供 event.py（业务视图层）共用。仅做事件列表的取数（read_events）
与归一/合并函数的转发（merge_events 实定义在 save_manager，此处 re-export 供 event.py
按 events_store.merge_events 调用）。事件结构：名称 / 进展节点[｛描述, 奖励?｝] / 关闭(布尔)。
依赖 save_manager（read_explore）。
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from store import save_manager as sm

# 事件在 explore.json 中的字段名（沿用旧字段，语义已升级为事件）
EVENTS_KEY = "任务摘要及进度"


def read_events(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """读取 slot 的全部事件（全量详细信息，含完整进展节点与奖励）；不存在返回 []。"""
    return sm.read_explore(slot, save_dir).get(EVENTS_KEY) or []


# 归一/合并逻辑实定义在 save_manager（纯函数，write_explore 直接用），此处转发以保持
# events_store.merge_events 既有接口供 event.py 调用，避免 save_manager↔events_store 循环 import。
merge_events = sm.merge_events
