#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事实驱动的任务图创建、扩展、发现与固定点归约。"""
import copy
from collections import defaultdict

from settle.domain_events import EventRequest, QUEST_LIFECYCLE_CHANGED, QUEST_NODE_COMPLETED
from settle.quest_conditions import evaluate_condition, referenced_facts
from settle.quest_models import new_runtime, normalize_quest_definition, normalize_node
from settle.quest_validator import (build_fact_index, validate_extension,
                                    validate_quest_definition)
from settle.world_facts import register_definitions


def create_quest(world_facts, quest_state, raw_definition, hidden=False):
    definition = normalize_quest_definition(raw_definition)
    quest_id = definition["quest_id"]
    if quest_id in quest_state["definitions"]:
        raise ValueError(f"任务ID【{quest_id}】已存在")
    register_definitions(world_facts, definition.get("fact_definitions"))
    validate_quest_definition(definition, world_facts, quest_state)
    quest_state["definitions"][quest_id] = definition
    quest_state["runtimes"][quest_id] = new_runtime(definition, hidden)
    return definition


def discover_quest(quest_state, quest_id):
    definition = quest_state.get("definitions", {}).get(quest_id)
    runtime = quest_state.get("runtimes", {}).get(quest_id)
    if not definition or not runtime:
        raise ValueError(f"未知任务【{quest_id}】")
    if runtime.get("lifecycle") != "hidden":
        return False, definition
    runtime["lifecycle"] = "active"
    return True, definition


def _incremental_extension(previous, raw):
    quest_id = previous["quest_id"]
    extension_id = raw.get("扩展点") or raw.get("extension_id")
    if extension_id not in previous["nodes"] or not previous["nodes"][extension_id].get("extension"):
        raise ValueError(f"任务【{quest_id}】扩展点无效【{extension_id}】")
    raw_nodes = raw.get("节点") if "节点" in raw else raw.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("线索扩展须提供新增 节点")
    starts = raw.get("起始节点") if "起始节点" in raw else raw.get("start_nodes")
    starts = list(starts) if isinstance(starts, list) else ([starts] if starts else [])
    if not starts:
        raise ValueError("线索扩展须提供扩展分支的 起始节点")
    candidate = copy.deepcopy(previous)
    candidate["version"] = int(raw.get("版本") or raw.get("version") or previous.get("version", 1) + 1)
    for raw_node in raw_nodes:
        node = normalize_node(raw_node)
        if node["node_id"] in candidate["nodes"]:
            raise ValueError(f"线索扩展新增节点ID已存在【{node['node_id']}】")
        candidate["nodes"][node["node_id"]] = node
    for node_id in starts:
        if node_id not in candidate["nodes"]:
            raise ValueError(f"线索扩展起始节点不存在【{node_id}】")
    candidate["nodes"][extension_id]["next"] = starts
    candidate["nodes"][extension_id]["extension"] = False
    definitions = raw.get("事实定义") if "事实定义" in raw else raw.get("fact_definitions")
    if definitions:
        candidate["fact_definitions"].extend(copy.deepcopy(definitions))
    return candidate, extension_id


def extend_quest(world_facts, quest_state, raw_extension):
    if not isinstance(raw_extension, dict):
        raise ValueError("线索扩展须为对象")
    full = raw_extension.get("任务") or raw_extension.get("definition")
    quest_id = (full or {}).get("任务ID") or (full or {}).get("quest_id") \
        or raw_extension.get("任务ID") or raw_extension.get("quest_id")
    previous = quest_state.get("definitions", {}).get(quest_id)
    runtime = quest_state.get("runtimes", {}).get(quest_id)
    if not previous or not runtime:
        raise ValueError(f"未知任务【{quest_id}】")
    extension_id = raw_extension.get("扩展点") or raw_extension.get("extension_id")
    if not extension_id:
        raise ValueError(f"任务【{quest_id}】线索扩展须指定 扩展点")
    if full:
        candidate = normalize_quest_definition(full)
    else:
        candidate, extension_id = _incremental_extension(previous, raw_extension)
    if extension_id not in previous["nodes"] or not previous["nodes"][extension_id].get("extension"):
        raise ValueError(f"任务【{quest_id}】扩展点无效【{extension_id}】")
    if extension_id in set(runtime.get("activated_extension_ids") or []):
        raise ValueError(f"任务【{quest_id}】扩展点【{extension_id}】已激活")
    expanded = candidate.get("nodes", {}).get(extension_id) or {}
    if expanded.get("extension") or not expanded.get("next"):
        raise ValueError(f"任务【{quest_id}】扩展后须为扩展点【{extension_id}】接入后继节点")
    register_definitions(world_facts, candidate.get("fact_definitions"))
    validate_extension(previous, candidate, runtime, world_facts, quest_state)
    quest_state["definitions"][quest_id] = candidate
    runtime["definition_version"] = candidate["version"]
    if extension_id:
        runtime.setdefault("activated_extension_ids", []).append(extension_id)
    return candidate


def _predecessors(definition):
    result = defaultdict(set)
    for node_id, node in definition["nodes"].items():
        for target in node.get("next") or []:
            result[target].add(node_id)
    return result


def _eligible(definition, node_id, completed, predecessors):
    node = definition["nodes"][node_id]
    required = list(node.get("requires") or predecessors.get(node_id) or [])
    if not required:
        return node_id in definition.get("start_nodes", [])
    if node.get("join") == "any":
        return any(item in completed for item in required)
    return all(item in completed for item in required)


def reduce_quest(world_facts, quest_state, quest_id):
    definition = quest_state.get("definitions", {}).get(quest_id)
    runtime = quest_state.get("runtimes", {}).get(quest_id)
    if not definition or not runtime or runtime.get("lifecycle") != "active":
        return [], [], [], []
    completed = set(runtime.get("completed_node_ids") or [])
    claimed = set(runtime.get("claimed_reward_ids") or [])
    activated = set(runtime.get("activated_extension_ids") or [])
    predecessors = _predecessors(definition)
    mutations = []
    events = []
    notices = []
    hints = []
    changed = True
    while changed:
        changed = False
        for node_id, node in definition["nodes"].items():
            if node_id in completed or not _eligible(definition, node_id, completed, predecessors):
                continue
            if node.get("extension") and node_id not in activated:
                if evaluate_condition(node.get("condition"), world_facts, completed):
                    hint = {
                        "类型": "任务扩展",
                        "任务ID": quest_id,
                        "线索": definition["name"],
                        "扩展点": node_id,
                        "提示": f"线索【{definition['name']}】即将进入扩展点【{node_id}】，须先用 quest-prepare 准备扩展",
                    }
                    if hint not in hints:
                        hints.append(hint)
                continue
            if not evaluate_condition(node.get("condition"), world_facts, completed):
                continue
            completed.add(node_id)
            runtime.setdefault("completed_node_ids", []).append(node_id)
            changed = True
            reward = node.get("reward") or {}
            reward_id = reward.get("reward_id")
            if reward_id and reward_id not in claimed:
                mutations.extend(copy.deepcopy(reward.get("mutations") or []))
                claimed.add(reward_id)
                runtime.setdefault("claimed_reward_ids", []).append(reward_id)
            mutations.extend(copy.deepcopy(node.get("effects") or []))
            events.append(EventRequest(QUEST_NODE_COMPLETED, {
                "quest_id": quest_id,
                "node_id": node_id,
                "summary": node.get("summary") or "",
            }))
            if node.get("visible", True):
                notices.append({
                    "quest_id": quest_id,
                    "quest_name": definition["name"],
                    "kind": "updated",
                    "node_id": node_id,
                    "summary": node.get("summary") or "",
                    "lifecycle": node.get("outcome"),
                })
            outcome = node.get("outcome")
            if outcome:
                before = runtime.get("lifecycle")
                runtime["lifecycle"] = outcome
                runtime["closed_reason"] = node.get("summary") or None
                events.append(EventRequest(QUEST_LIFECYCLE_CHANGED, {
                    "quest_id": quest_id, "before": before, "after": outcome,
                }))
                changed = False
                break
    return mutations, events, notices, hints


def reduce_affected_quests(world_facts, quest_state, fact_key=None, quest_id=None):
    if quest_id:
        quest_ids = [quest_id]
    elif fact_key:
        quest_ids = build_fact_index(quest_state).get(fact_key, [])
    else:
        quest_ids = list(quest_state.get("definitions", {}))
    mutations, events, notices, hints = [], [], [], []
    for current in quest_ids:
        produced = reduce_quest(world_facts, quest_state, current)
        mutations.extend(produced[0])
        events.extend(produced[1])
        notices.extend(produced[2])
        hints.extend(produced[3])
    return mutations, events, notices, hints


def potential_progress_hints(world_facts, quest_state):
    hints = []
    for quest_id, definition in quest_state.get("definitions", {}).items():
        runtime = quest_state.get("runtimes", {}).get(quest_id) or {}
        if runtime.get("lifecycle") != "active":
            continue
        completed = set(runtime.get("completed_node_ids") or [])
        predecessors = _predecessors(definition)
        for node_id, node in definition["nodes"].items():
            if node_id in completed or not _eligible(definition, node_id, completed, predecessors):
                continue
            unknown = []
            for fact_key in referenced_facts(node.get("condition")):
                record = world_facts.get("records", {}).get(fact_key)
                if not record or record.get("status") in ("unknown", "alleged"):
                    unknown.append(fact_key)
            if unknown:
                hints.append({
                    "类型": "潜在线索变化",
                    "任务ID": quest_id,
                    "线索": definition["name"],
                    "节点ID": node_id,
                    "候选事实": sorted(unknown),
                    "提示": "若剧情已确认这些语义事实，请在 judge 中提交事实变更；当前尚未推进节点",
                })
    return hints
