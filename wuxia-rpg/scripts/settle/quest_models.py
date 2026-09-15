#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务蓝图与槽位运行状态的规范化模型。"""
import copy
import hashlib


VERSION = 1
TERMINAL_LIFECYCLES = {"resolved", "failed", "closed"}


def empty_quest_state():
    return {"version": VERSION, "definitions": {}, "runtimes": {}, "legacy_imported": False}


def normalize_quest_state(data):
    if not isinstance(data, dict):
        return empty_quest_state()
    definitions = data.get("definitions")
    runtimes = data.get("runtimes")
    return {
        "version": VERSION,
        "definitions": copy.deepcopy(definitions) if isinstance(definitions, dict) else {},
        "runtimes": copy.deepcopy(runtimes) if isinstance(runtimes, dict) else {},
        "legacy_imported": bool(data.get("legacy_imported")),
    }


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def normalize_reward(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        return {"reward_id": None, "summary": raw, "mutations": []}
    if not isinstance(raw, dict):
        raise ValueError("节点奖励须为对象或字符串")
    reward_id = raw.get("reward_id") or raw.get("奖励ID")
    mutations = raw.get("mutations")
    if mutations is None:
        mutations = raw.get("状态变更") or []
    if not isinstance(mutations, list) or any(not isinstance(item, dict) for item in mutations):
        raise ValueError("节点奖励的状态变更须为对象数组")
    if mutations and (not isinstance(reward_id, str) or not reward_id.strip()):
        raise ValueError("含状态变更的节点奖励须提供稳定 奖励ID")
    return {
        "reward_id": reward_id.strip() if isinstance(reward_id, str) else None,
        "summary": raw.get("summary") or raw.get("描述") or raw.get("摘要"),
        "mutations": copy.deepcopy(mutations),
    }


def normalize_node(raw):
    if not isinstance(raw, dict):
        raise ValueError("任务节点须为对象")
    node_id = raw.get("node_id") or raw.get("节点ID")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("任务节点须提供稳定 节点ID")
    outcome = raw.get("outcome") or raw.get("终局")
    outcome_alias = {"解决": "resolved", "失败": "failed", "关闭": "closed"}
    outcome = outcome_alias.get(outcome, outcome)
    if outcome is not None and outcome not in TERMINAL_LIFECYCLES:
        raise ValueError(f"节点【{node_id}】终局类型不合法")
    join = raw.get("join") or raw.get("汇合规则") or "all"
    if join not in ("all", "any"):
        raise ValueError(f"节点【{node_id}】汇合规则须为 all/any")
    effects = raw.get("effects")
    if effects is None:
        effects = raw.get("效果") or []
    if not isinstance(effects, list) or any(not isinstance(item, dict) for item in effects):
        raise ValueError(f"节点【{node_id}】效果须为 mutation 对象数组")
    return {
        "node_id": node_id.strip(),
        "requires": _as_list(raw.get("requires") if "requires" in raw else raw.get("前置节点")),
        "join": join,
        "condition": copy.deepcopy(raw.get("condition") if "condition" in raw else raw.get("完成条件") or {}),
        "summary": raw.get("summary") or raw.get("完成摘要") or "",
        "next": _as_list(raw.get("next") if "next" in raw else raw.get("后继节点")),
        "outcome": outcome,
        "visible": bool(raw.get("visible", raw.get("玩家可见", True))),
        "extension": bool(raw.get("extension", raw.get("扩展点", False))),
        "reward": normalize_reward(raw.get("reward") if "reward" in raw else raw.get("奖励")),
        "effects": copy.deepcopy(effects),
    }


def normalize_quest_definition(raw):
    if not isinstance(raw, dict):
        raise ValueError("任务蓝图须为对象")
    quest_id = raw.get("quest_id") or raw.get("任务ID")
    name = raw.get("name") or raw.get("名称")
    if not isinstance(quest_id, str) or not quest_id.strip():
        raise ValueError("任务蓝图须提供稳定 任务ID")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"任务【{quest_id}】须提供 名称")
    raw_nodes = raw.get("nodes")
    if raw_nodes is None:
        raw_nodes = raw.get("节点")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError(f"任务【{quest_id}】须提供非空节点数组")
    nodes = {}
    for raw_node in raw_nodes:
        node = normalize_node(raw_node)
        if node["node_id"] in nodes:
            raise ValueError(f"任务【{quest_id}】节点ID重复【{node['node_id']}】")
        nodes[node["node_id"]] = node
    starts = _as_list(raw.get("start_nodes") if "start_nodes" in raw else raw.get("起始节点"))
    if not starts:
        starts = [node_id for node_id, node in nodes.items() if not node["requires"]]
    definitions = raw.get("fact_definitions")
    if definitions is None:
        definitions = raw.get("事实定义") or []
    if not isinstance(definitions, list):
        raise ValueError(f"任务【{quest_id}】事实定义须为数组")
    return {
        "quest_id": quest_id.strip(),
        "version": int(raw.get("version") or raw.get("版本") or 1),
        "name": name.strip(),
        "intro": raw.get("intro") or raw.get("引子") or "",
        "hidden_goal": raw.get("hidden_goal") or raw.get("隐藏目标") or "",
        "start_nodes": starts,
        "nodes": nodes,
        "fact_definitions": copy.deepcopy(definitions),
        "legacy": bool(raw.get("legacy")),
    }


def new_runtime(definition, hidden=False):
    return {
        "quest_id": definition["quest_id"],
        "definition_version": definition["version"],
        "lifecycle": "hidden" if hidden else "active",
        "completed_node_ids": [],
        "claimed_reward_ids": [],
        "activated_extension_ids": [],
        "discovered_at": None,
        "closed_reason": None,
    }


def _legacy_id(name):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return f"legacy:{digest}"


def import_legacy_quests(explore, quest_state):
    if quest_state.get("legacy_imported"):
        return False
    legacy_clues = [
        clue for clue in (explore.get("任务摘要及进度") or [])
        if isinstance(clue, dict) and clue.get("名称")
    ]
    if not legacy_clues:
        return False
    for clue in legacy_clues:
        if not isinstance(clue, dict) or not clue.get("名称"):
            continue
        quest_id = _legacy_id(str(clue["名称"]))
        if quest_id in quest_state["definitions"]:
            continue
        nodes = []
        completed = []
        claimed = []
        progress = clue.get("进展节点")
        progress = progress if isinstance(progress, list) else []
        for index, raw_node in enumerate(progress, 1):
            node = raw_node if isinstance(raw_node, dict) else {"描述": str(raw_node)}
            node_id = f"legacy-node-{index}"
            is_last = index == len(progress)
            reward = node.get("奖励")
            reward_id = f"{quest_id}:reward:{index}" if reward is not None else None
            nodes.append({
                "node_id": node_id,
                "requires": [f"legacy-node-{index - 1}"] if index > 1 else [],
                "join": "all",
                "condition": {},
                "summary": node.get("描述", ""),
                "next": [f"legacy-node-{index + 1}"] if not is_last else [],
                "outcome": ("closed" if clue.get("关闭") and is_last else None),
                "visible": True,
                "extension": bool(is_last and not clue.get("关闭")),
                "reward": ({"reward_id": reward_id, "summary": reward, "mutations": []}
                           if reward is not None else None),
                "effects": [],
            })
            completed.append(node_id)
            if reward_id:
                claimed.append(reward_id)
        if not nodes:
            nodes.append({
                "node_id": "legacy-summary", "requires": [], "join": "all", "condition": {},
                "summary": clue.get("描述") or "线索已记录", "next": [],
                "outcome": "closed" if clue.get("关闭") else None, "visible": True,
                "extension": not bool(clue.get("关闭")), "reward": None, "effects": [],
            })
            completed.append("legacy-summary")
        definition = {
            "quest_id": quest_id, "version": 1, "name": clue["名称"], "intro": "",
            "hidden_goal": "", "start_nodes": [nodes[0]["node_id"]],
            "nodes": {node["node_id"]: node for node in nodes}, "fact_definitions": [],
            "legacy": True,
        }
        runtime = new_runtime(definition)
        runtime["completed_node_ids"] = completed
        runtime["claimed_reward_ids"] = claimed
        runtime["lifecycle"] = "closed" if clue.get("关闭") else "active"
        quest_state["definitions"][quest_id] = definition
        quest_state["runtimes"][quest_id] = runtime
    quest_state["legacy_imported"] = True
    return True
