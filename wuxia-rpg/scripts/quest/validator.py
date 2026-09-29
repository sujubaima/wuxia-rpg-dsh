#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务蓝图图结构、事实定义与扩展历史校验。"""
from collections import defaultdict, deque
from quest.conditions import referenced_facts, referenced_nodes, validate_condition
from quest.world_facts import (FACT_STATUSES, fact_key_parts, normalize_definition,
                               validate_fact_value)


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
    return {node_id for node_id, node in definition["nodes"].items() if node.get("terminal")}


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


def _exits(definition, activated=frozenset()):
    # 已激活的扩展点不可再扩展，不算出口（激活后 extension 正常已置 False，此处防御异常写法）
    return _terminals(definition) | {
        node_id for node_id, node in definition["nodes"].items()
        if (node.get("extension") and node_id not in activated)
        or node.get("close_condition") == {}
    }


def _can_reach_exit(definition, allowed=None, activated=frozenset()):
    allowed = set(definition["nodes"]) if allowed is None else set(allowed)
    reverse = defaultdict(set)
    for node_id, node in definition["nodes"].items():
        if node_id not in allowed:
            continue
        for target in node.get("next") or []:
            if target in allowed:
                reverse[target].add(node_id)
    queue = deque(node_id for node_id in _exits(definition, activated) if node_id in allowed)
    seen = set(queue)
    while queue:
        node_id = queue.popleft()
        for previous in reverse[node_id]:
            if previous not in seen:
                seen.add(previous)
                queue.append(previous)
    return seen


def _validate_graph(definition, activated_extension_ids=frozenset()):
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
        if (not node.get("terminal") and not node.get("next")
                and not node.get("extension") and not unconditional_close):
            raise ValueError(f"任务【{quest_name}】存在断头节点【{node_id}】")
        if node.get("terminal") and node.get("next"):
            raise ValueError(f"任务【{quest_name}】终局节点【{node_id}】不得再有后继")
    terminals = _terminals(definition)
    open_extensions = {
        node_id for node_id, node in nodes.items()
        if node.get("extension") and node_id not in activated_extension_ids
    }
    if not terminals and not open_extensions:
        raise ValueError(f"任务【{quest_name}】至少须有一个终局或未触发的扩展点")
    reachable = _reachable(definition)
    unreachable = set(nodes) - reachable
    if unreachable:
        raise ValueError(f"任务【{quest_name}】存在不可达节点：{sorted(unreachable)}")
    can_finish = _can_reach_exit(definition, activated=activated_extension_ids)
    dead = {
        node_id for node_id in reachable
        if node_id not in can_finish
        and not (nodes[node_id].get("extension") and node_id not in activated_extension_ids)
    }
    if dead:
        raise ValueError(f"任务【{quest_name}】存在无法抵达终局的节点：{sorted(dead)}")
    return predecessors


_COMPARATORS = ("eq", "ne", "in", "exists", "gt", "gte", "lt", "lte", "status")
_ORDERED_COMPARATORS = {"gt", "gte", "lt", "lte"}


def _condition_leaves(condition, negated=False):
    if not isinstance(condition, dict) or condition in ({},):
        return
    if "fact" in condition:
        yield condition, negated
        return
    for key in ("all", "any"):
        for child in condition.get(key) or []:
            yield from _condition_leaves(child, negated)
    if "not" in condition:
        yield from _condition_leaves(condition["not"], not negated)


def _validate_fact_leaf(leaf, fact_definition, own_outcome_keys, negated=False):
    fact_key = leaf["fact"].strip()
    _, _, predicate, _ = fact_key_parts(fact_key)
    if predicate == "outcome" and fact_key in own_outcome_keys:
        raise ValueError("不得以本任务自身 outcome 作为完成/关闭依据；请使用具体选择事实")
    operator = next(key for key in _COMPARATORS if key in leaf)
    value_type = fact_definition["value_type"]
    expected = leaf[operator]
    if operator == "exists":
        if expected is False or negated:
            raise ValueError(
                "任务条件禁止 exists:false 或其等价否定；实体不存在须由已确认的 .exists == false 事实表达"
            )
        return
    if operator == "status":
        if expected not in FACT_STATUSES:
            raise ValueError(f"status 值不合法【{expected}】")
        return
    if operator in _ORDERED_COMPARATORS:
        if value_type != "number":
            raise ValueError(f"比较符【{operator}】仅支持 number，当前为【{value_type}】")
        validate_fact_value(fact_definition, expected)
        return
    if operator == "in":
        if value_type == "set":
            raise ValueError("set 事实不支持 in；请使用规范化后的 eq/ne")
        if not isinstance(expected, (list, tuple, set)) or not expected:
            raise ValueError("比较符 in 须提供非空数组")
        for value in expected:
            validate_fact_value(fact_definition, value)
        return
    if operator in ("eq", "ne"):
        validate_fact_value(fact_definition, expected)
        return
    raise ValueError(f"不支持比较符【{operator}】")


def _validate_facts(definition, world_facts):
    quest_name = definition["name"]
    registered = world_facts.get("definitions", {})
    for fact_key in quest_fact_keys(definition):
        if fact_key not in registered:
            raise ValueError(f"任务【{quest_name}】引用未注册事实【{fact_key}】")
    own_outcome_keys = {
        normalized["fact_key"]
        for normalized in (
            normalize_definition(raw) for raw in definition.get("fact_definitions") or []
        )
        if normalized["predicate"] == "outcome"
    }
    for node_id, node in definition.get("nodes", {}).items():
        for field, label in (("condition", "完成条件"),
                             ("close_condition", "关闭条件")):
            for leaf, negated in _condition_leaves(node.get(field)):
                fact_key = leaf["fact"].strip()
                try:
                    _validate_fact_leaf(
                        leaf, registered[fact_key], own_outcome_keys, negated
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"任务【{quest_name}】节点【{node_id}】{label}事实【{fact_key}】：{exc}"
                    ) from exc
        for mutation in _node_mutations(node):
            if mutation.get("类型") not in ("事实", "事实-写入", "事实-修订"):
                continue
            fact_key = mutation.get("事实") or mutation.get("fact_key")
            if "值" not in mutation and "value" not in mutation:
                continue
            value = mutation.get("值") if "值" in mutation else mutation.get("value")
            try:
                validate_fact_value(registered[fact_key], value)
                status = mutation.get("状态", mutation.get("status", "verified"))
                if status not in FACT_STATUSES:
                    raise ValueError(f"状态【{status}】不合法")
            except ValueError as exc:
                raise ValueError(
                    f"任务【{quest_name}】节点【{node_id}】事实效果【{fact_key}】：{exc}"
                ) from exc


def validate_quest_definition(definition, world_facts, quest_state=None,
                              activated_extension_ids=frozenset()):
    _validate_graph(definition, activated_extension_ids)
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
                    "close_summary", "next", "terminal", "visible", "extension",
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
    # 本次扩展点即将激活：不计算在“未触发扩展点”内，防止扩展后任务永久悬死
    activated = set(runtime.get("activated_extension_ids") or []) | {extension_id}
    return validate_quest_definition(candidate, world_facts, quest_state, activated)
