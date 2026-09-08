#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事件系统业务视图层 —— 大世界事件（旧「任务」）的查询/展示入口。

事件存于 explore.json 的「任务摘要及进度」字段。底层读写/合并已下沉 events_store
（供 save_manager 同步与本章复用）；本脚本只保留事件业务语义视图（进行中/已关闭/精简/
全貌）与 CLI。供 engine 侧/GM 查询调用。事件结构：名称 / 进展节点[｛描述, 奖励?｝] /
关闭(布尔)。详见 references/wuxia-rpg-exploration.md「事件系统」。

用法：
  python3 scripts/world/event.py read-tasks <slot>   # 输出事件列表（兼容旧命令名）
  python3 scripts/world/event.py ongoing <slot>     # 只输出进行中事件（关闭=false），
                                                     # 每项 {名称, 节点描述:[...]}，
                                                     # 用于 GM 不记得手上有哪些进行中线时快速回顾
  python3 scripts/world/event.py view <slot>        # 事件栏精简视图（进行中+已关闭）
  python3 scripts/world/event.py summary <slot>    # 输出当前存档全部经历与事件
                                                     # （经历概括 + 事件全量含已关闭），供 GM 回顾剧情全貌
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from store import save_manager as sm
from store import events_store as es


def read_events(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """读取 slot 的全部事件（全量详细信息，含完整进展节点与奖励）；不存在返回 []。"""
    return es.read_events(slot, save_dir)


def merge_events(existing, incoming):
    """按 名称 增量合并事件列表（转发 events_store.merge_events）。"""
    return es.merge_events(existing, incoming)


def _node_text(n):
    """取节点描述文本。节点可为字符串（纯描述）或字典（{描述, 奖励?}）。"""
    if isinstance(n, str):
        return n
    if isinstance(n, dict):
        return n.get("描述", "")
    return ""


def read_event(slot, name, save_dir=sm.DEFAULT_SAVE_DIR):
    """按名称读取单个事件的全部信息（完整进展节点含奖励）；无则返回 None。"""
    for e in read_events(slot, save_dir):
        if isinstance(e, dict) and e.get("名称") == name:
            return e
    return None


def read_event_view(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """读取事件栏展示用精简视图。

    返回 {"进行中": [...], "已关闭": [...]}：
    - 进行中（关闭=false）：每项 {名称, 节点描述: [节点描述...]}（仅节点描述，不含奖励）
    - 已关闭（关闭=true）：每项 {名称}（不展开节点）
    """
    ongoing, closed = [], []
    for e in read_events(slot, save_dir):
        if not isinstance(e, dict) or "名称" not in e:
            continue
        if e.get("关闭", False):
            closed.append({"名称": e["名称"]})
        else:
            nodes = e.get("进展节点") or []
            ongoing.append({
                "名称": e["名称"],
                "节点描述": [_node_text(n) for n in nodes],
            })
    return {"进行中": ongoing, "已关闭": closed}


def read_ongoing(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """只读取进行中事件（关闭=false）。每项 {名称, 节点描述:[...]}。
    供 GM 不记得手上有哪些进行中线时快速回顾。
    """
    return read_event_view(slot, save_dir)["进行中"]


def read_summary(slot, save_dir=sm.DEFAULT_SAVE_DIR):
    """读取存档全部经历与事件信息，供 GM 回顾当前剧情全貌。

    返回 {经历概括, 事件}：
    - 经历概括：explore.json 的 经历概括 字段（全量剧情概括，无则空串）
    - 事件：任务摘要及进度全量（含进行中与已关闭，完整进展节点与奖励）
    """
    exp = sm.read_explore(slot, save_dir)
    return {
        "经历概括": exp.get("经历概括") or "",
        "事件": exp.get(es.EVENTS_KEY) or [],
    }


def _cli(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "read-tasks":
        if len(argv) < 2:
            print("用法: read-tasks <slot>", file=sys.stderr)
            return 2
        print(json.dumps(read_events(argv[1]), ensure_ascii=False, indent=2))
        return 0
    if cmd == "read-event":
        if len(argv) < 3:
            print("用法: read-event <slot> <事件名>", file=sys.stderr)
            return 2
        print(json.dumps(read_event(argv[1], argv[2]), ensure_ascii=False, indent=2))
        return 0
    if cmd == "view":
        if len(argv) < 2:
            print("用法: view <slot>", file=sys.stderr)
            return 2
        print(json.dumps(read_event_view(argv[1]), ensure_ascii=False, indent=2))
        return 0
    if cmd == "ongoing":
        if len(argv) < 2:
            print("用法: ongoing <slot>", file=sys.stderr)
            return 2
        print(json.dumps(read_ongoing(argv[1]), ensure_ascii=False, indent=2))
        return 0
    if cmd == "summary":
        if len(argv) < 2:
            print("用法: summary <slot>", file=sys.stderr)
            return 2
        print(json.dumps(read_summary(argv[1]), ensure_ascii=False, indent=2))
        return 0
    print(f"未知命令: {cmd}\n可用: read-tasks | read-event | view | ongoing | summary", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
