#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务蓝图结构、可达性、事实覆盖与跨任务冲突校验。"""
from collections import defaultdict, deque
from itertools import product

from settle.quest_conditions import (condition_possible, referenced_facts,
                                     referenced_nodes, validate_condition,
                                     with_hypothetical_fact)


def _node_mutations(node):
    mutations = list(node.get("effects") or [])
    mutations.extend((node.get("reward") or {}).get("mutations") or [])
    return mutations


def quest_fact_keys(definition):
    keys = set()
    for node in definition.get("nodes", {}).values():
        keys.update(referenced_facts(node.get("condition")))
        for mutation in _node_mutations(node):
            if mutation.get("类型") not in ("事实", "事实-写入", "事实-修订"):
                continue
            key = mutation.get("事实") or mutation.get("fact_key")
            if isinstance(key, str):
                keys.add(key)
    return keys


def build_fact_index(quest_state):
    index = defaultdict(set)
    for quest_id, definition in quest_state.get("definitions", {}).items():
        for fact_key in quest_fact_keys(definition):
            index[fact_key].add(quest_id)
    return {key: sorted(value) for key, value in index.items()}


def _predecessors(definition):
    predecessors = defaultdict(set)
    for node_id, node in definition["nodes"].items():
        for target in node.get("next") or []:
            predecessors[target].add(node_id)
    return predecessors


def _requirements(definition, node_id, predecessors):
    node = definition["nodes"][node_id]
    return set(node.get("requires") or predecessors.get(node_id) or [])


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
        node_id for node_id, node in definition["nodes"].items() if node.get("extension")
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


def _possible_completion(definition, world_facts):
    completed = set()
    predecessors = _predecessors(definition)
    changed = True
    while changed:
        changed = False
        for node_id, node in definition["nodes"].items():
            if node_id in completed:
                continue
            required = _requirements(definition, node_id, predecessors)
            if not required:
                eligible = node_id in definition.get("start_nodes", [])
            elif node.get("join") == "any":
                eligible = bool(required & completed)
            else:
                eligible = required <= completed
            if eligible and condition_possible(node.get("condition"), world_facts, completed):
                completed.add(node_id)
                changed = True
    return completed


def _validate_graph(definition):
    quest_id = definition["quest_id"]
    nodes = definition["nodes"]
    if not definition.get("start_nodes"):
        raise ValueError(f"任务【{quest_id}】缺少起始节点")
    for start in definition["start_nodes"]:
        if start not in nodes:
            raise ValueError(f"任务【{quest_id}】起始节点不存在【{start}】")
    predecessors = _predecessors(definition)
    reward_ids = set()
    for node_id, node in nodes.items():
        validate_condition(node.get("condition"))
        for fact_node in referenced_nodes(node.get("condition")):
            if fact_node not in nodes:
                raise ValueError(f"任务【{quest_id}】节点【{node_id}】引用未知节点【{fact_node}】")
        for required in node.get("requires") or []:
            if required not in nodes:
                raise ValueError(f"任务【{quest_id}】节点【{node_id}】前置节点不存在【{required}】")
        for target in node.get("next") or []:
            if target not in nodes:
                raise ValueError(f"任务【{quest_id}】节点【{node_id}】后继不存在【{target}】")
        reward = node.get("reward") or {}
        reward_id = reward.get("reward_id")
        if reward_id:
            if reward_id in reward_ids:
                raise ValueError(f"任务【{quest_id}】奖励ID重复【{reward_id}】")
            reward_ids.add(reward_id)
        if not node.get("outcome") and not node.get("next") and not node.get("extension"):
            raise ValueError(f"任务【{quest_id}】存在断头节点【{node_id}】")
        if node.get("outcome") and node.get("next"):
            raise ValueError(f"任务【{quest_id}】终局节点【{node_id}】不得再有后继")
    terminals = _terminals(definition)
    if not terminals:
        raise ValueError(f"任务【{quest_id}】至少须有一个解决、失败或关闭终局")
    reachable = _reachable(definition)
    unreachable = set(nodes) - reachable
    if unreachable:
        raise ValueError(f"任务【{quest_id}】存在不可达节点：{sorted(unreachable)}")
    can_finish = _can_reach_exit(definition)
    dead = {
        node_id for node_id in reachable
        if node_id not in can_finish and not nodes[node_id].get("extension")
    }
    if dead:
        raise ValueError(f"任务【{quest_id}】存在无法抵达终局的节点：{sorted(dead)}")
    return predecessors


def _validate_facts(definition, world_facts):
    quest_id = definition["quest_id"]
    for fact_key in quest_fact_keys(definition):
        if fact_key not in world_facts.get("definitions", {}):
            raise ValueError(f"任务【{quest_id}】引用未注册事实【{fact_key}】")
    possible = _possible_completion(definition, world_facts)
    if not (_exits(definition) & possible):
        raise ValueError(f"任务【{quest_id}】与当前已确认事实冲突，已无可达终局")
    condition_facts = set()
    for node in definition["nodes"].values():
        condition_facts.update(referenced_facts(node.get("condition")))
    unresolved = []
    for fact_key in sorted(condition_facts):
        fact_definition = world_facts["definitions"].get(fact_key) or {}
        record = world_facts.get("records", {}).get(fact_key)
        if fact_definition.get("value_type") != "enum":
            continue
        if record and record.get("status") == "verified":
            continue
        unresolved.append((fact_key, fact_definition.get("allowed_values") or []))
    combinations = 1
    for _, values in unresolved:
        combinations *= len(values)
    if combinations > 256:
        raise ValueError(f"任务【{quest_id}】未决枚举组合超过256，须拆分蓝图或缩小事实域")
    for values in product(*(domain for _, domain in unresolved)) if unresolved else ():
        hypothetical = world_facts
        labels = []
        for (fact_key, _), value in zip(unresolved, values):
            hypothetical = with_hypothetical_fact(hypothetical, fact_key, value)
            labels.append(f"{fact_key}={value}")
        possible = _possible_completion(definition, hypothetical)
        if not (_exits(definition) & possible):
            raise ValueError(
                f"任务【{quest_id}】未覆盖事实枚举组合【{', '.join(labels)}】时的终局或扩展出口"
            )


def _fact_effects(definition):
    effects = defaultdict(set)
    for node in definition.get("nodes", {}).values():
        for mutation in _node_mutations(node):
            if mutation.get("类型") not in ("事实", "事实-写入", "事实-修订"):
                continue
            key = mutation.get("事实") or mutation.get("fact_key")
            if key:
                effects[key].add(repr(mutation.get("值")))
    return effects


def _validate_cross_quest(definition, quest_state, world_facts):
    candidate = _fact_effects(definition)
    for other_id, other in quest_state.get("definitions", {}).items():
        if other_id == definition["quest_id"]:
            continue
        other_effects = _fact_effects(other)
        for fact_key in set(candidate) & set(other_effects):
            if candidate[fact_key] != other_effects[fact_key]:
                fact_definition = world_facts.get("definitions", {}).get(fact_key) or {}
                if fact_definition.get("revision_policy") != "free":
                    raise ValueError(
                        f"任务【{definition['quest_id']}】与任务【{other_id}】对事实【{fact_key}】声明互斥效果"
                    )


def validate_quest_definition(definition, world_facts, quest_state=None):
    _validate_graph(definition)
    _validate_facts(definition, world_facts)
    _validate_cross_quest(definition, quest_state or {}, world_facts)
    return True


def validate_extension(previous, candidate, runtime, world_facts, quest_state):
    if previous["quest_id"] != candidate["quest_id"]:
        raise ValueError("线索扩展不得改变任务ID")
    if candidate["version"] <= previous.get("version", 1):
        raise ValueError(f"任务【{candidate['quest_id']}】扩展版本必须递增")
    completed = set(runtime.get("completed_node_ids") or [])
    claimed = set(runtime.get("claimed_reward_ids") or [])
    for node_id in completed:
        if node_id not in candidate["nodes"]:
            raise ValueError(f"线索扩展不得删除已完成节点【{node_id}】")
        old = previous["nodes"].get(node_id)
        new = candidate["nodes"][node_id]
        for key in ("condition", "summary", "outcome", "reward", "effects"):
            if old.get(key) != new.get(key):
                raise ValueError(f"线索扩展不得改写已完成节点【{node_id}】的【{key}】")
    candidate_rewards = {
        (node.get("reward") or {}).get("reward_id")
        for node in candidate["nodes"].values()
    }
    missing_rewards = claimed - candidate_rewards
    if missing_rewards:
        raise ValueError(f"线索扩展不得删除已领取奖励：{sorted(missing_rewards)}")
    return validate_quest_definition(candidate, world_facts, quest_state)
