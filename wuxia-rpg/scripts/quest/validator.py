#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务蓝图图结构、事实定义与扩展历史校验。"""
from collections import defaultdict, deque
from quest.conditions import referenced_facts, referenced_nodes, validate_condition


def _node_mutations(node):
    mutations = list(node.get("effects") or [])
    mutations.extend((node.get("reward") or {}).get("mutations") or [])
    return mutations


def quest_fact_keys(definition):
    keys = set()
    for node in definition.get("nodes", {}).values():
        keys.update(referenced_facts(node.get("condition")))
        keys.update(referenced_facts(node.get("close_condition")))
        for mutation in _node_mutations(node):
            if mutation.get("类型") not in ("事实", "事实-写入", "事实-修订"):
                continue
            key = mutation.get("事实") or mutation.get("fact_key")
            if isinstance(key, str):
                keys.add(key)
    return keys


def build_fact_index(quest_state):
    index = defaultdict(set)
    for quest_name, definition in quest_state.get("definitions", {}).items():
        for fact_key in quest_fact_keys(definition):
            index[fact_key].add(quest_name)
    return {key: sorted(value) for key, value in index.items()}


def _predecessors(definition):
    predecessors = defaultdict(set)
    for node_id, node in definition["nodes"].items():
        for target in node.get("next") or []:
            predecessors[target].add(node_id)
    return predecessors


def _terminals(definition):
    return {node_id for node_id, node in definition["nodes"].items() if node.get("outcome")}


def _reachable(definition, starts=None, allowed=None):
    allowed = set(definition["nodes"]) if allowed is None else set(allowed)
    queue = deque(starts or definition["start_nodes"])
    seen = set()
    while queue:
        node_id = queue.popleft()
        if node_id in seen or node_id not in allowed:
            continue
        seen.add(node_id)
        queue.extend(definition["nodes"][node_id].get("next") or [])
    return seen


def _exits(definition):
    return _terminals(definition) | {
        node_id for node_id, node in definition["nodes"].items()
        if node.get("extension") or node.get("close_condition") == {}
    }


def _can_reach_exit(definition, allowed=None):
    allowed = set(definition["nodes"]) if allowed is None else set(allowed)
    reverse = defaultdict(set)
    for node_id, node in definition["nodes"].items():
        if node_id not in allowed:
            continue
        for target in node.get("next") or []:
            if target in allowed:
                reverse[target].add(node_id)
    queue = deque(node_id for node_id in _exits(definition) if node_id in allowed)
    seen = set(queue)
    while queue:
        node_id = queue.popleft()
        for previous in reverse[node_id]:
            if previous not in seen:
                seen.add(previous)
                queue.append(previous)
    return seen


def _validate_graph(definition):
    quest_name = definition["name"]
    nodes = definition["nodes"]
    if not definition.get("start_nodes"):
        raise ValueError(f"任务【{quest_name}】缺少起始节点")
    for start in definition["start_nodes"]:
        if start not in nodes:
            raise ValueError(f"任务【{quest_name}】起始节点不存在【{start}】")
    predecessors = _predecessors(definition)
    reward_ids = set()
    for node_id, node in nodes.items():
        validate_condition(node.get("condition"))
        validate_condition(node.get("close_condition"))
        referenced = referenced_nodes(node.get("condition"))
        referenced.update(referenced_nodes(node.get("close_condition")))
        for fact_node in referenced:
            if fact_node not in nodes:
                raise ValueError(f"任务【{quest_name}】节点【{node_id}】引用未知节点【{fact_node}】")
        for required in node.get("requires") or []:
            if required not in nodes:
                raise ValueError(f"任务【{quest_name}】节点【{node_id}】前置节点不存在【{required}】")
        for target in node.get("next") or []:
            if target not in nodes:
                raise ValueError(f"任务【{quest_name}】节点【{node_id}】后继不存在【{target}】")
        reward = node.get("reward") or {}
        reward_id = reward.get("reward_id")
        if reward_id:
            if reward_id in reward_ids:
                raise ValueError(f"任务【{quest_name}】奖励ID重复【{reward_id}】")
            reward_ids.add(reward_id)
        unconditional_close = node.get("close_condition") == {}
        if (not node.get("outcome") and not node.get("next")
                and not node.get("extension") and not unconditional_close):
            raise ValueError(f"任务【{quest_name}】存在断头节点【{node_id}】")
        if node.get("outcome") and node.get("next"):
            raise ValueError(f"任务【{quest_name}】终局节点【{node_id}】不得再有后继")
    terminals = _terminals(definition)
    if not terminals:
        raise ValueError(f"任务【{quest_name}】至少须有一个解决、失败或关闭终局")
    reachable = _reachable(definition)
    unreachable = set(nodes) - reachable
    if unreachable:
        raise ValueError(f"任务【{quest_name}】存在不可达节点：{sorted(unreachable)}")
    can_finish = _can_reach_exit(definition)
    dead = {
        node_id for node_id in reachable
        if node_id not in can_finish and not nodes[node_id].get("extension")
    }
    if dead:
        raise ValueError(f"任务【{quest_name}】存在无法抵达终局的节点：{sorted(dead)}")
    return predecessors


def _validate_facts(definition, world_facts):
    quest_name = definition["name"]
    for fact_key in quest_fact_keys(definition):
        if fact_key not in world_facts.get("definitions", {}):
            raise ValueError(f"任务【{quest_name}】引用未注册事实【{fact_key}】")


def validate_quest_definition(definition, world_facts, quest_state=None):
    _validate_graph(definition)
    _validate_facts(definition, world_facts)
    return True


def validate_extension(previous, candidate, runtime, world_facts, quest_state, extension_id):
    if previous["name"] != candidate["name"]:
        raise ValueError(
            f"线索扩展不得改名；现有名称【{previous['name']}】"
        )
    if candidate["version"] <= previous.get("version", 1):
        raise ValueError(f"任务【{candidate['name']}】扩展版本必须递增")
    completed = set(runtime.get("completed_node_ids") or [])
    closed = set(runtime.get("closed_node_ids") or [])
    blocked = set(runtime.get("blocked_node_ids") or [])
    claimed = set(runtime.get("claimed_reward_ids") or [])
    historical = completed | closed | blocked
    for node_id in historical:
        if node_id not in candidate["nodes"]:
            raise ValueError(f"线索扩展不得删除已有状态节点【{node_id}】")
        old = previous["nodes"].get(node_id)
        new = candidate["nodes"][node_id]
        for key in ("requires", "join", "condition", "summary", "close_condition",
                    "close_summary", "next", "outcome", "visible", "extension",
                    "reward", "effects"):
            if old.get(key) != new.get(key):
                raise ValueError(f"线索扩展不得改写已有状态节点【{node_id}】的【{key}】")
    if extension_id in closed or extension_id in blocked:
        raise ValueError(f"任务【{candidate['name']}】扩展点【{extension_id}】已关闭")
    candidate_rewards = {
        (node.get("reward") or {}).get("reward_id")
        for node in candidate["nodes"].values()
    }
    missing_rewards = claimed - candidate_rewards
    if missing_rewards:
        raise ValueError(f"线索扩展不得删除已领取奖励：{sorted(missing_rewards)}")
    return validate_quest_definition(candidate, world_facts, quest_state)
