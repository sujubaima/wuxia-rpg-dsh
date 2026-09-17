#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务运行状态到旧线索栏结构及结算摘要的投影。"""
from collections import OrderedDict


_TERMINAL = {"resolved", "failed", "closed"}


def project_clues(quest_state):
    clues = []
    for quest_name, definition in quest_state.get("definitions", {}).items():
        runtime = quest_state.get("runtimes", {}).get(quest_name) or {}
        if runtime.get("lifecycle") == "hidden":
            continue
        completed = set(runtime.get("completed_node_ids") or [])
        closed = set(runtime.get("closed_node_ids") or [])
        settled = runtime.get("settled_node_ids") or list(
            runtime.get("completed_node_ids") or []
        )
        nodes = []
        for node_id in settled:
            node = definition.get("nodes", {}).get(node_id) or {}
            if not node.get("visible", True):
                continue
            if node_id in closed:
                nodes.append({"描述": node.get("close_summary") or ""})
                continue
            if node_id not in completed:
                continue
            entry = {"描述": node.get("summary") or ""}
            reward = node.get("reward") or {}
            if reward.get("summary") is not None:
                entry["奖励"] = reward["summary"]
            nodes.append(entry)
        clue = {"名称": quest_name, "进展节点": nodes}
        if runtime.get("lifecycle") in _TERMINAL:
            clue["关闭"] = True
        clues.append(clue)
    return clues


def notice_results(notices):
    grouped = OrderedDict()
    for notice in notices or []:
        quest_name = notice.get("quest_name")
        if not quest_name:
            continue
        kind = notice.get("kind") or "updated"
        if kind not in ("discovered", "updated"):
            continue
        group = grouped.setdefault(quest_name, {
            "name": quest_name,
            "kind": kind,
        })
        if kind == "discovered":
            group["kind"] = "discovered"
    results = []
    for group in grouped.values():
        suffix = "已发现" if group["kind"] == "discovered" else "已更新"
        text = f"线索【{group['name']}】{suffix}"
        results.append({"ok": True, "msg": text, "变更": text})
    return results
