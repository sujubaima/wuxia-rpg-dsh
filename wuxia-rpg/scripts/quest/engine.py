#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事实驱动的任务图创建、扩展、发现与固定点归约。"""
import copy
from collections import defaultdict

from quest.events import (EventRequest, QUEST_LIFECYCLE_CHANGED,
                          QUEST_NODE_BLOCKED, QUEST_NODE_CLOSED,
                          QUEST_NODE_COMPLETED)
from quest.conditions import condition_possible, evaluate_condition, referenced_facts
from quest.models import (TERMINAL_LIFECYCLES, new_runtime,
                          normalize_quest_definition, normalize_node, normalize_reward)
from quest.validator import (build_fact_index, validate_extension,
                             validate_quest_definition)
from quest.world_facts import normalize_definition, register_definitions


def _require_fact_descriptions(definitions):
    for raw in definitions or []:
        definition = normalize_definition(raw)
        if not definition.get("description"):
            raise ValueError(f"事实定义【{definition['fact_key']}】须提供非空 描述")


def create_quest(world_facts, quest_state, raw_definition, hidden=False):
    definition = normalize_quest_definition(raw_definition)
    quest_name = definition["name"]
    if quest_name in quest_state["definitions"]:
        raise ValueError(f"线索名称【{quest_name}】已存在")
    _require_fact_descriptions(definition.get("fact_definitions"))
    register_definitions(world_facts, definition.get("fact_definitions"))
    validate_quest_definition(definition, world_facts, quest_state)
    quest_state["definitions"][quest_name] = definition
    quest_state["runtimes"][quest_name] = new_runtime(definition, hidden)
    return definition


def discover_quest(quest_state, quest_name):
    definition = quest_state.get("definitions", {}).get(quest_name)
    runtime = quest_state.get("runtimes", {}).get(quest_name)
    if not definition or not runtime:
        raise ValueError(f"未知任务【{quest_name}】")
    if runtime.get("lifecycle") != "hidden":
        return False, definition
    runtime["lifecycle"] = "active"
    return True, definition


def _incremental_extension(previous, raw):
    if "quest_id" in raw or "任务ID" in raw:
        raise ValueError("线索扩展不再接受 任务ID，请仅使用 名称")
    quest_name = previous["name"]
    extension_name = raw.get("name") or raw.get("名称")
    if not isinstance(extension_name, str) or extension_name.strip() != quest_name:
        raise ValueError(f"线索扩展须使用现有名称【{quest_name}】")
    extension_id = raw.get("扩展点") or raw.get("extension_id")
    if extension_id not in previous["nodes"] or not previous["nodes"][extension_id].get("extension"):
        raise ValueError(f"任务【{quest_name}】扩展点无效【{extension_id}】")
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
        _require_fact_descriptions(definitions)
        candidate["fact_definitions"].extend(copy.deepcopy(definitions))
    return candidate, extension_id


def extend_quest(world_facts, quest_state, raw_extension):
    if not isinstance(raw_extension, dict):
        raise ValueError("线索扩展须为对象")
    if "quest_id" in raw_extension or "任务ID" in raw_extension:
        raise ValueError("线索扩展不再接受 任务ID，请仅使用 名称")
    if "任务" in raw_extension or "definition" in raw_extension:
        raise ValueError("线索扩展不再接受全量定义，请使用增量模式：只传 扩展点/起始节点/新增节点")
    quest_name = raw_extension.get("名称") or raw_extension.get("name")
    if not isinstance(quest_name, str) or not quest_name.strip():
        raise ValueError("线索扩展须提供非空 名称")
    quest_name = quest_name.strip()
    previous = quest_state.get("definitions", {}).get(quest_name)
    runtime = quest_state.get("runtimes", {}).get(quest_name)
    if not previous or not runtime:
        raise ValueError(f"未知任务【{quest_name}】")
    extension_id = raw_extension.get("扩展点") or raw_extension.get("extension_id")
    if not extension_id:
        raise ValueError(f"任务【{quest_name}】线索扩展须指定 扩展点")
    candidate, extension_id = _incremental_extension(previous, raw_extension)
    if extension_id not in previous["nodes"] or not previous["nodes"][extension_id].get("extension"):
        raise ValueError(f"任务【{quest_name}】扩展点无效【{extension_id}】")
    if extension_id in set(runtime.get("activated_extension_ids") or []):
        raise ValueError(f"任务【{quest_name}】扩展点【{extension_id}】已激活")
    unavailable = set(runtime.get("closed_node_ids") or []) | set(runtime.get("blocked_node_ids") or [])
    if extension_id in unavailable:
        raise ValueError(f"任务【{quest_name}】扩展点【{extension_id}】已关闭")
    expanded = candidate.get("nodes", {}).get(extension_id) or {}
    if expanded.get("extension") or not expanded.get("next"):
        raise ValueError(f"任务【{quest_name}】扩展后须为扩展点【{extension_id}】接入后继节点")
    register_definitions(world_facts, candidate.get("fact_definitions"))
    validate_extension(
        previous, candidate, runtime, world_facts, quest_state, extension_id
    )
    quest_state["definitions"][quest_name] = candidate
    runtime["definition_version"] = candidate["version"]
    if extension_id:
        runtime.setdefault("activated_extension_ids", []).append(extension_id)
    return candidate


def modify_quest_rewards(world_facts, quest_state, raw):
    """修改未完成节点的奖励内容（quest-prepare「修改」操作）。

    只允许改挂起节点的奖励：已完成/关闭/阻断节点冻结；新奖励ID不得复用已领取
    或其他节点的奖励ID（防重复领取/静默丢失）。修改即蓝图版本 +1。
    """
    if not isinstance(raw, dict):
        raise ValueError("线索修改须为对象")
    if "quest_id" in raw or "任务ID" in raw:
        raise ValueError("线索修改不再接受 任务ID，请仅使用 名称")
    quest_name = (raw.get("名称") or raw.get("name") or "").strip()
    if not quest_name:
        raise ValueError("线索修改须提供非空 名称")
    definition = quest_state.get("definitions", {}).get(quest_name)
    runtime = quest_state.get("runtimes", {}).get(quest_name)
    if not definition or not runtime:
        raise ValueError(f"未知任务【{quest_name}】")
    entries = raw.get("奖励修改") if "奖励修改" in raw else raw.get("reward_changes")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"任务【{quest_name}】线索修改须提供非空 奖励修改 数组")
    historical = (set(runtime.get("completed_node_ids") or [])
                  | set(runtime.get("closed_node_ids") or [])
                  | set(runtime.get("blocked_node_ids") or []))
    claimed = set(runtime.get("claimed_reward_ids") or [])
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("奖励修改项须为对象")
        extra = set(entry) - {"节点ID", "奖励"}
        if extra:
            raise ValueError(f"奖励修改项出现非预期字段：{'、'.join(sorted(extra))}")
        node_id = (entry.get("节点ID") or entry.get("node_id") or "").strip()
        if not node_id:
            raise ValueError("奖励修改项须提供 节点ID")
        if node_id not in definition["nodes"]:
            raise ValueError(f"任务【{quest_name}】节点不存在【{node_id}】")
        if node_id in historical:
            raise ValueError(f"任务【{quest_name}】节点【{node_id}】已完成/关闭/阻断，不得修改其奖励")
        reward = normalize_reward(entry.get("奖励") if "奖励" in entry else entry.get("reward"))
        reward_id = (reward or {}).get("reward_id")
        if reward_id:
            if reward_id in claimed:
                raise ValueError(f"任务【{quest_name}】奖励ID【{reward_id}】已被领取，不得复用")
            other_ids = {
                (definition["nodes"][other].get("reward") or {}).get("reward_id")
                for other in definition["nodes"] if other != node_id
            }
            if reward_id in other_ids:
                raise ValueError(f"任务【{quest_name}】奖励ID【{reward_id}】与其他节点重复")
        definition["nodes"][node_id]["reward"] = reward
    definition["version"] = int(definition.get("version", 1)) + 1
    return definition


def _predecessors(definition):
    result = defaultdict(set)
    for node_id, node in definition["nodes"].items():
        for target in node.get("next") or []:
            result[target].add(node_id)
    return result


def _requirements(definition, node_id, predecessors):
    node = definition["nodes"][node_id]
    return set(node.get("requires") or predecessors.get(node_id) or [])


def _eligible(definition, node_id, completed, predecessors):
    node = definition["nodes"][node_id]
    required = _requirements(definition, node_id, predecessors)
    if not required:
        return node_id in definition.get("start_nodes", [])
    if node.get("join") == "any":
        return bool(required & completed)
    return required <= completed


def _path_blocked(definition, node_id, closed, blocked, predecessors):
    required = _requirements(definition, node_id, predecessors)
    if not required:
        return False
    unavailable = closed | blocked
    if definition["nodes"][node_id].get("join") == "any":
        return required <= unavailable
    return bool(required & unavailable)


def reduce_quest(world_facts, quest_state, quest_name):
    definition = quest_state.get("definitions", {}).get(quest_name)
    runtime = quest_state.get("runtimes", {}).get(quest_name)
    if not definition or not runtime or runtime.get("lifecycle") != "active":
        return [], [], [], []
    completed = set(runtime.get("completed_node_ids") or [])
    closed = set(runtime.get("closed_node_ids") or [])
    blocked = set(runtime.get("blocked_node_ids") or [])
    claimed = set(runtime.get("claimed_reward_ids") or [])
    activated = set(runtime.get("activated_extension_ids") or [])
    settled = runtime.setdefault(
        "settled_node_ids", list(runtime.get("completed_node_ids") or [])
    )
    predecessors = _predecessors(definition)
    mutations = []
    events = []
    notices = []
    hints = []
    terminated = False
    changed = True
    while changed and not terminated:
        changed = False
        for node_id in definition["nodes"]:
            if node_id in completed or node_id in closed or node_id in blocked:
                continue
            if _path_blocked(definition, node_id, closed, blocked, predecessors):
                blocked.add(node_id)
                runtime.setdefault("blocked_node_ids", []).append(node_id)
                events.append(EventRequest(QUEST_NODE_BLOCKED, {
                    "quest_name": quest_name, "node_id": node_id,
                }))
                changed = True

        for node_id, node in definition["nodes"].items():
            if node_id in completed or node_id in closed or node_id in blocked:
                continue
            if not _eligible(definition, node_id, completed, predecessors):
                continue
            close_condition = node.get("close_condition")
            if (close_condition is not None
                    and evaluate_condition(close_condition, world_facts, completed)):
                closed.add(node_id)
                runtime.setdefault("closed_node_ids", []).append(node_id)
                if node_id not in settled:
                    settled.append(node_id)
                changed = True
                events.append(EventRequest(QUEST_NODE_CLOSED, {
                    "quest_name": quest_name,
                    "node_id": node_id,
                    "summary": node.get("close_summary") or "",
                }))
                if node.get("visible", True):
                    notices.append({
                        "quest_name": quest_name,
                        "kind": "updated",
                        "node_id": node_id,
                        "summary": node.get("close_summary") or "",
                        "node_state": "closed",
                    })
                continue
            if node.get("extension") and node_id not in activated:
                if evaluate_condition(node.get("condition"), world_facts, completed):
                    hint = {
                        "类型": "任务扩展",
                        "线索": quest_name,
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
            if node_id not in settled:
                settled.append(node_id)
            changed = True
            reward = node.get("reward") or {}
            reward_id = reward.get("reward_id")
            if reward_id and reward_id not in claimed:
                for mutation in reward.get("mutations") or []:
                    tagged = copy.deepcopy(mutation)
                    tagged["_来源"] = {"任务": quest_name, "节点": node_id,
                                     "类别": "奖励", "奖励ID": reward_id}
                    mutations.append(tagged)
                claimed.add(reward_id)
                runtime.setdefault("claimed_reward_ids", []).append(reward_id)
            for mutation in node.get("effects") or []:
                tagged = copy.deepcopy(mutation)
                tagged["_来源"] = {"任务": quest_name, "节点": node_id, "类别": "效果"}
                mutations.append(tagged)
            events.append(EventRequest(QUEST_NODE_COMPLETED, {
                "quest_name": quest_name,
                "node_id": node_id,
                "summary": node.get("summary") or "",
            }))
            if node.get("visible", True):
                notices.append({
                    "quest_name": quest_name,
                    "kind": "updated",
                    "node_id": node_id,
                    "summary": node.get("summary") or "",
                })
            if node.get("terminal"):
                before = runtime.get("lifecycle")
                runtime["lifecycle"] = "ended"
                runtime["closed_reason"] = node.get("summary") or None
                events.append(EventRequest(QUEST_LIFECYCLE_CHANGED, {
                    "quest_name": quest_name, "before": before, "after": "ended",
                }))
                terminated = True
                break

    all_nodes = set(definition["nodes"])
    settled_states = completed | closed | blocked
    if runtime.get("lifecycle") == "active" and all_nodes <= settled_states:
        before = runtime.get("lifecycle")
        runtime["lifecycle"] = "ended"
        last_closed = next((
            definition["nodes"][node_id].get("close_summary")
            for node_id in reversed(settled)
            if node_id in closed
        ), None)
        runtime["closed_reason"] = last_closed or "所有可推进路径均已中断"
        events.append(EventRequest(QUEST_LIFECYCLE_CHANGED, {
            "quest_name": quest_name, "before": before, "after": "ended",
        }))
    # 任务定局时补 ended 标记，使对外提示为「已结束」而非「已更新」；
    # 仅在本轮已有可见节点通知时追加，不改变静默收尾的广播边界。
    if runtime.get("lifecycle") in TERMINAL_LIFECYCLES and notices:
        notices.append({"quest_name": quest_name, "kind": "ended"})
    return mutations, events, notices, hints


def reduce_affected_quests(world_facts, quest_state, fact_key=None, quest_name=None):
    if quest_name:
        quest_names = [quest_name]
    elif fact_key:
        quest_names = build_fact_index(quest_state).get(fact_key, [])
    else:
        quest_names = list(quest_state.get("definitions", {}))
    mutations, events, notices, hints = [], [], [], []
    for current in quest_names:
        produced = reduce_quest(world_facts, quest_state, current)
        mutations.extend(produced[0])
        events.extend(produced[1])
        notices.extend(produced[2])
        hints.extend(produced[3])
    return mutations, events, notices, hints


def pending_extension_gates(world_facts, quest_state):
    """扫描 active 任务中"已行进至却未扩展"的扩展点。

    判定：节点带扩展点标志、未激活、未关闭/阻塞、前置已齐（eligible）、
    且完成条件在当前 world_facts 下已成立。返回 (任务名, 节点ID) 列表，
    供 judge 结算收尾打回 GM——防止扩展点空转导致任务悬死。
    """
    gates = []
    for quest_name, definition in quest_state.get("definitions", {}).items():
        runtime = quest_state.get("runtimes", {}).get(quest_name) or {}
        if runtime.get("lifecycle") != "active":
            continue
        completed = set(runtime.get("completed_node_ids") or [])
        unavailable = (set(runtime.get("closed_node_ids") or [])
                       | set(runtime.get("blocked_node_ids") or []))
        activated = set(runtime.get("activated_extension_ids") or [])
        predecessors = _predecessors(definition)
        for node_id, node in definition["nodes"].items():
            if not node.get("extension"):
                continue
            if node_id in completed or node_id in unavailable or node_id in activated:
                continue
            if not _eligible(definition, node_id, completed, predecessors):
                continue
            if evaluate_condition(node.get("condition"), world_facts, completed):
                gates.append((quest_name, node_id))
    return gates


def _hidden_entry_hint(world_facts, quest_name, definition):
    """隐藏线索入场提示：入口节点条件已被已确认事实满足时，提醒 GM 可发现该线索。"""
    for node_id in definition.get("start_nodes", []):
        condition = (definition["nodes"].get(node_id) or {}).get("condition") or {}
        # 无条件入口无机械信号，发现时机由 GM 按叙事判断
        if not condition or not evaluate_condition(condition, world_facts, set()):
            continue
        node = definition["nodes"][node_id]
        return [{
            "类型": "隐藏线索",
            "线索": quest_name,
            "入口节点": node_id,
            "引子": definition.get("intro") or "",
            "隐藏目标": definition.get("hidden_goal") or "",
            "入口摘要": node.get("summary") or "",
            "提示": (f"隐藏线索【{definition['name']}】入场条件已满足，"
                     "可在 judge 中经 线索-发现 转入进行中"),
        }]
    return []


def potential_progress_hints(world_facts, quest_state):
    hints = []
    candidates = {}
    for quest_name, definition in quest_state.get("definitions", {}).items():
        runtime = quest_state.get("runtimes", {}).get(quest_name) or {}
        if runtime.get("lifecycle") == "hidden":
            hints.extend(_hidden_entry_hint(world_facts, quest_name, definition))
            continue
        if runtime.get("lifecycle") != "active":
            continue
        completed = set(runtime.get("completed_node_ids") or [])
        unavailable = (set(runtime.get("closed_node_ids") or [])
                       | set(runtime.get("blocked_node_ids") or []))
        predecessors = _predecessors(definition)
        for node_id, node in definition["nodes"].items():
            if (node_id in completed or node_id in unavailable
                    or not _eligible(definition, node_id, completed, predecessors)):
                continue
            conditions = [node.get("condition")]
            if node.get("close_condition") is not None:
                conditions.append(node.get("close_condition"))
            for condition in conditions:
                if not condition_possible(condition, world_facts, completed):
                    continue
                for fact_key in sorted(referenced_facts(condition)):
                    record = world_facts.get("records", {}).get(fact_key)
                    if record and record.get("status") not in ("unknown", "alleged"):
                        continue
                    clue = candidates.setdefault(fact_key, {}).setdefault(quest_name, {
                        "名称": quest_name,
                        "节点ID列表": [],
                    })
                    if node_id not in clue["节点ID列表"]:
                        clue["节点ID列表"].append(node_id)
    definitions = world_facts.get("definitions", {})
    for fact_key in sorted(candidates):
        fact_definition = definitions.get(fact_key) or {}
        description = fact_definition.get("description") or ""
        hints.append({
            "类型": "潜在线索变化",
            "候选事实": fact_key,
            "事实描述": description if isinstance(description, str) else "",
            "影响线索": [
                {
                    **clue,
                    "节点ID列表": sorted(clue["节点ID列表"]),
                }
                for _, clue in sorted(candidates[fact_key].items())
            ],
            "提示": "若剧情已确认该语义事实，请在 judge 中提交事实变更；当前尚未推进相关节点",
        })
    return hints
