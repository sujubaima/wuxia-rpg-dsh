#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务蓝图与槽位运行状态的规范化模型。"""
import copy


VERSION = 4
TERMINAL_LIFECYCLES = {"ended"}
# 旧三值终局（不区分好坏结局，仅作记录标签）统一归一为布尔终局
_LEGACY_OUTCOMES = {"解决": True, "失败": True, "关闭": True,
                    "resolved": True, "failed": True, "closed": True}
_LEGACY_LIFECYCLES = {"resolved": "ended", "failed": "ended", "closed": "ended"}


def empty_quest_state():
    return {"version": VERSION, "definitions": {}, "runtimes": {}, "legacy_imported": False}


def _normalize_stored_definition(raw_definition, name):
    definition = copy.deepcopy(raw_definition)
    definition.pop("quest_id", None)
    definition.pop("任务ID", None)
    definition["name"] = name
    nodes = definition.get("nodes")
    if isinstance(nodes, dict):
        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            node.setdefault("close_condition", None)
            node.setdefault("close_summary", None)
            if "outcome" in node:  # v3 迁移：三值终局归一为布尔
                node["terminal"] = bool(node.pop("outcome"))
            node.setdefault("terminal", False)
    return definition


def _normalize_stored_runtime(raw_runtime):
    runtime = copy.deepcopy(raw_runtime) if isinstance(raw_runtime, dict) else {}
    runtime.pop("quest_id", None)
    runtime.pop("任务ID", None)
    lifecycle = runtime.get("lifecycle")
    if lifecycle in _LEGACY_LIFECYCLES:  # v3 迁移：终局生命周期归一为 ended
        runtime["lifecycle"] = _LEGACY_LIFECYCLES[lifecycle]
    completed = list(runtime.get("completed_node_ids") or [])
    runtime["completed_node_ids"] = completed
    runtime["closed_node_ids"] = list(runtime.get("closed_node_ids") or [])
    runtime["blocked_node_ids"] = list(runtime.get("blocked_node_ids") or [])
    runtime["settled_node_ids"] = list(runtime.get("settled_node_ids") or completed)
    runtime["claimed_reward_ids"] = list(runtime.get("claimed_reward_ids") or [])
    runtime["activated_extension_ids"] = list(runtime.get("activated_extension_ids") or [])
    runtime.setdefault("discovered_at", None)
    runtime.setdefault("closed_reason", None)
    return runtime


def normalize_quest_state(data):
    if not isinstance(data, dict):
        return empty_quest_state()
    raw_definitions = data.get("definitions")
    raw_runtimes = data.get("runtimes")
    raw_definitions = raw_definitions if isinstance(raw_definitions, dict) else {}
    raw_runtimes = raw_runtimes if isinstance(raw_runtimes, dict) else {}
    definitions = {}
    runtimes = {}
    sources = {}
    for old_key, raw_definition in raw_definitions.items():
        if not isinstance(raw_definition, dict):
            continue
        name = raw_definition.get("name") or raw_definition.get("名称") or old_key
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"旧任务【{old_key}】缺少有效线索名称，无法迁移")
        name = name.strip()
        if name in definitions:
            raise ValueError(
                f"旧任务【{sources[name]}】与【{old_key}】线索名称重复【{name}】，无法迁移"
            )
        definitions[name] = _normalize_stored_definition(raw_definition, name)
        runtimes[name] = _normalize_stored_runtime(
            raw_runtimes.get(old_key) or raw_runtimes.get(name) or {}
        )
        sources[name] = old_key
    return {
        "version": VERSION,
        "definitions": definitions,
        "runtimes": runtimes,
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
    terminal = raw.get("terminal", raw.get("终局"))
    if terminal is None:
        terminal = False
    if terminal in _LEGACY_OUTCOMES:  # 兼容旧三值写法（解决/失败/关闭）
        terminal = True
    if not isinstance(terminal, bool):
        raise ValueError(f"节点【{node_id}】终局须为布尔值")
    join = raw.get("join") or raw.get("汇合规则") or "all"
    if join not in ("all", "any"):
        raise ValueError(f"节点【{node_id}】汇合规则须为 all/any")
    effects = raw.get("effects")
    if effects is None:
        effects = raw.get("效果") or []
    if not isinstance(effects, list) or any(not isinstance(item, dict) for item in effects):
        raise ValueError(f"节点【{node_id}】效果须为 mutation 对象数组")
    has_close_condition = "close_condition" in raw or "关闭条件" in raw
    has_close_summary = "close_summary" in raw or "关闭描述" in raw
    if not has_close_condition or not has_close_summary:
        raise ValueError(f"节点【{node_id}】须显式提供 关闭条件 和 关闭描述")
    close_condition = (
        raw.get("close_condition") if "close_condition" in raw else raw.get("关闭条件")
    )
    close_summary = (
        raw.get("close_summary") if "close_summary" in raw else raw.get("关闭描述")
    )
    if (close_condition is None) != (close_summary is None):
        raise ValueError(f"节点【{node_id}】关闭条件和关闭描述须同时为 null 或同时提供")
    if close_condition is not None:
        if not isinstance(close_condition, dict):
            raise ValueError(f"节点【{node_id}】关闭条件须为对象或 null")
        if not isinstance(close_summary, str) or not close_summary.strip():
            raise ValueError(f"节点【{node_id}】关闭描述须为非空字符串")
        close_summary = close_summary.strip()
    return {
        "node_id": node_id.strip(),
        "requires": _as_list(raw.get("requires") if "requires" in raw else raw.get("前置节点")),
        "join": join,
        "condition": copy.deepcopy(raw.get("condition") if "condition" in raw else raw.get("完成条件") or {}),
        "summary": raw.get("summary") or raw.get("完成摘要") or "",
        "close_condition": copy.deepcopy(close_condition),
        "close_summary": close_summary,
        "next": _as_list(raw.get("next") if "next" in raw else raw.get("后继节点")),
        "terminal": terminal,
        "visible": bool(raw.get("visible", raw.get("玩家可见", True))),
        "extension": bool(raw.get("extension", raw.get("扩展点", False))),
        "reward": normalize_reward(raw.get("reward") if "reward" in raw else raw.get("奖励")),
        "effects": copy.deepcopy(effects),
    }


def normalize_quest_definition(raw):
    if not isinstance(raw, dict):
        raise ValueError("任务蓝图须为对象")
    if "quest_id" in raw or "任务ID" in raw:
        raise ValueError("任务蓝图不再接受 任务ID，请仅使用 名称")
    name = raw.get("name") or raw.get("名称")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("任务蓝图须提供非空 名称")
    name = name.strip()
    raw_nodes = raw.get("nodes")
    if raw_nodes is None:
        raw_nodes = raw.get("节点")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError(f"任务【{name}】须提供非空节点数组")
    nodes = {}
    for raw_node in raw_nodes:
        node = normalize_node(raw_node)
        if node["node_id"] in nodes:
            raise ValueError(f"任务【{name}】节点ID重复【{node['node_id']}】")
        nodes[node["node_id"]] = node
    starts = _as_list(raw.get("start_nodes") if "start_nodes" in raw else raw.get("起始节点"))
    if not starts:
        starts = [node_id for node_id, node in nodes.items() if not node["requires"]]
    definitions = raw.get("fact_definitions")
    if definitions is None:
        definitions = raw.get("事实定义") or []
    if not isinstance(definitions, list):
        raise ValueError(f"任务【{name}】事实定义须为数组")
    hook = raw.get("hook") or raw.get("由头")
    anchor_regions = _as_list(
        raw.get("anchor_regions") if "anchor_regions" in raw else raw.get("锚点地区"))
    hook_fact = raw.get("hook_fact") or raw.get("由头事实") or None
    if hook_fact is not None and (not isinstance(hook_fact, str) or not hook_fact.strip()):
        raise ValueError(f"任务【{name}】由头事实须为非空字符串")
    return {
        "version": int(raw.get("version") or raw.get("版本") or 1),
        "name": name,
        "intro": raw.get("intro") or raw.get("引子") or "",
        "hidden_goal": raw.get("hidden_goal") or raw.get("隐藏目标") or "",
        "hook": hook if isinstance(hook, str) else "",
        "anchor_regions": [r for r in anchor_regions if isinstance(r, str) and r.strip()],
        "hook_fact": hook_fact.strip() if isinstance(hook_fact, str) else None,
        "start_nodes": starts,
        "nodes": nodes,
        "fact_definitions": copy.deepcopy(definitions),
        "legacy": bool(raw.get("legacy")),
    }


def new_runtime(definition, hidden=False):
    return {
        "definition_version": definition["version"],
        "lifecycle": "hidden" if hidden else "active",
        "completed_node_ids": [],
        "closed_node_ids": [],
        "blocked_node_ids": [],
        "settled_node_ids": [],
        "claimed_reward_ids": [],
        "activated_extension_ids": [],
        "discovered_at": None,
        "closed_reason": None,
    }


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
        quest_name = str(clue["名称"]).strip()
        if not quest_name or quest_name in quest_state["definitions"]:
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
            reward_id = f"{quest_name}:reward:{index}" if reward is not None else None
            nodes.append({
                "node_id": node_id,
                "requires": [f"legacy-node-{index - 1}"] if index > 1 else [],
                "join": "all",
                "condition": {},
                "summary": node.get("描述", ""),
                "close_condition": None,
                "close_summary": None,
                "next": [f"legacy-node-{index + 1}"] if not is_last else [],
                "terminal": bool(clue.get("关闭") and is_last),
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
                "summary": clue.get("描述") or "线索已记录",
                "close_condition": None, "close_summary": None, "next": [],
                "terminal": bool(clue.get("关闭")), "visible": True,
                "extension": not bool(clue.get("关闭")), "reward": None, "effects": [],
            })
            completed.append("legacy-summary")
        definition = {
            "version": 1, "name": quest_name, "intro": "",
            "hidden_goal": "", "start_nodes": [nodes[0]["node_id"]],
            "nodes": {node["node_id"]: node for node in nodes}, "fact_definitions": [],
            "legacy": True,
        }
        runtime = new_runtime(definition)
        runtime["completed_node_ids"] = completed
        runtime["settled_node_ids"] = list(completed)
        runtime["claimed_reward_ids"] = claimed
        runtime["lifecycle"] = "ended" if clue.get("关闭") else "active"
        quest_state["definitions"][quest_name] = definition
        quest_state["runtimes"][quest_name] = runtime
    quest_state["legacy_imported"] = True
    return True
