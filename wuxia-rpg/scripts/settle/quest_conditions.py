#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务条件的受限 DSL：求值、事实引用与保守可满足性判断。"""
import copy


_COMPARATORS = ("eq", "ne", "in", "exists", "gt", "gte", "lt", "lte", "status")
_FACT_STATUSES = {"unknown", "alleged", "verified", "refuted"}


def referenced_facts(condition):
    found = set()
    if not isinstance(condition, dict):
        return found
    if isinstance(condition.get("fact"), str):
        found.add(condition["fact"])
    for key in ("all", "any"):
        for child in condition.get(key) or []:
            found.update(referenced_facts(child))
    if "not" in condition:
        found.update(referenced_facts(condition["not"]))
    return found


def referenced_nodes(condition):
    found = set()
    if not isinstance(condition, dict):
        return found
    if isinstance(condition.get("node"), str):
        found.add(condition["node"])
    for key in ("all", "any"):
        for child in condition.get(key) or []:
            found.update(referenced_nodes(child))
    if "not" in condition:
        found.update(referenced_nodes(condition["not"]))
    return found


def validate_condition(condition):
    if condition in (None, {}):
        return
    if not isinstance(condition, dict):
        raise ValueError("任务条件须为对象")
    logical = [key for key in ("all", "any", "not") if key in condition]
    leaves = [key for key in ("fact", "node") if key in condition]
    if len(logical) + len(leaves) != 1:
        raise ValueError("任务条件每层须且只能包含 all/any/not/fact/node 之一")
    if "all" in condition or "any" in condition:
        key = "all" if "all" in condition else "any"
        children = condition[key]
        if not isinstance(children, list) or not children:
            raise ValueError(f"任务条件 {key} 须为非空数组")
        for child in children:
            validate_condition(child)
        return
    if "not" in condition:
        validate_condition(condition["not"])
        return
    if "node" in condition:
        if not isinstance(condition["node"], str) or not condition["node"].strip():
            raise ValueError("节点条件须提供 node")
        extra = set(condition) - {"node", "completed"}
        if extra:
            raise ValueError(f"节点条件存在未知字段：{sorted(extra)}")
        if "completed" in condition and not isinstance(condition["completed"], bool):
            raise ValueError("节点条件 completed 须为 bool")
        return
    if not isinstance(condition.get("fact"), str) or not condition["fact"].strip():
        raise ValueError("事实条件须提供 fact")
    comparators = [key for key in _COMPARATORS if key in condition]
    if len(comparators) != 1:
        raise ValueError("事实条件须且只能提供一个比较操作")
    extra = set(condition) - {"fact", comparators[0]}
    if extra:
        raise ValueError(f"事实条件存在未知字段：{sorted(extra)}")
    operator = comparators[0]
    if operator == "exists" and not isinstance(condition[operator], bool):
        raise ValueError("事实条件 exists 须为 bool")
    if operator == "in" and not isinstance(condition[operator], (list, tuple, set)):
        raise ValueError("事实条件 in 须为数组")
    if operator == "status" and condition[operator] not in _FACT_STATUSES:
        raise ValueError(f"事实条件 status 不合法【{condition[operator]}】")


def _compare(value, operator, expected, exists):
    if operator == "exists":
        return exists is bool(expected)
    if not exists:
        return False
    if operator == "eq":
        return value == expected
    if operator == "ne":
        return value != expected
    if operator == "in":
        return isinstance(expected, (list, tuple, set)) and value in expected
    try:
        if operator == "gt":
            return value > expected
        if operator == "gte":
            return value >= expected
        if operator == "lt":
            return value < expected
        if operator == "lte":
            return value <= expected
    except TypeError:
        return False
    return False


def _fact_leaf(condition, world_facts):
    record = (world_facts.get("records") or {}).get(condition["fact"])
    status = record.get("status") if record else None
    exists = bool(record and status in ("verified", "refuted", "alleged"))
    if "status" in condition:
        return status, "eq", condition["status"], record is not None
    operator = next(key for key in _COMPARATORS if key in condition)
    return (record.get("value") if record else None), operator, condition[operator], exists and status == "verified"


def evaluate_condition(condition, world_facts, completed_nodes=None):
    if condition in (None, {}):
        return True
    completed = set(completed_nodes or [])
    if "all" in condition:
        return all(evaluate_condition(child, world_facts, completed) for child in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(child, world_facts, completed) for child in condition["any"])
    if "not" in condition:
        return not evaluate_condition(condition["not"], world_facts, completed)
    if "node" in condition:
        return (condition["node"] in completed) is bool(condition.get("completed", True))
    value, operator, expected, exists = _fact_leaf(condition, world_facts)
    return _compare(value, operator, expected, exists)


def condition_possible(condition, world_facts, completed_nodes=None):
    """保守判断条件未来是否可能成立；unknown/alleged 不提前判死。"""
    if condition in (None, {}):
        return True
    completed = set(completed_nodes or [])
    if "all" in condition:
        return all(condition_possible(child, world_facts, completed) for child in condition["all"])
    if "any" in condition:
        return any(condition_possible(child, world_facts, completed) for child in condition["any"])
    if "not" in condition:
        child = condition["not"]
        if evaluate_condition(child, world_facts, completed):
            return False
        return True
    if "node" in condition:
        wanted = bool(condition.get("completed", True))
        return (condition["node"] in completed) if wanted else True
    record = (world_facts.get("records") or {}).get(condition["fact"])
    if not record or record.get("status") in ("unknown", "alleged"):
        return True
    return evaluate_condition(condition, world_facts, completed)


def with_hypothetical_fact(world_facts, fact_key, value):
    result = copy.deepcopy(world_facts)
    result.setdefault("records", {})[fact_key] = {
        "fact_id": fact_key,
        "fact_key": fact_key,
        "value": copy.deepcopy(value),
        "status": "verified",
        "source": "validator",
        "evidence_ids": [],
        "updated_at": None,
    }
    return result
