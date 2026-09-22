#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新档预设任务的扁平目录加载与静态完整性校验。"""
from pathlib import Path

from common.json_io import read_json
from quest.conditions import referenced_facts
from quest.engine import create_quest, potential_progress_hints
from quest.models import empty_quest_state, normalize_quest_definition
from quest.triggers import bootstrap_mechanical_facts
from quest.validator import quest_fact_keys
from quest.world_facts import empty_world_facts, normalize_definition


_MECHANICAL_ENTRY_FACTS = {
    "player.region@world",
    "world.time@world",
    "party.stamina@world",
}
_FACT_MUTATION_TYPES = {"事实", "事实-写入", "事实-修订"}


def _fact_key(mutation):
    if not isinstance(mutation, dict) or mutation.get("类型") not in _FACT_MUTATION_TYPES:
        return None
    key = mutation.get("事实") or mutation.get("fact_key")
    return key if isinstance(key, str) and key.strip() else None


def _node_mutations(node):
    mutations = list(node.get("effects") or [])
    mutations.extend((node.get("reward") or {}).get("mutations") or [])
    return mutations


def _declared_fact_keys(definition):
    return {
        normalize_definition(raw)["fact_key"]
        for raw in definition.get("fact_definitions") or []
    }


def _is_mechanical_entry_fact(fact_key):
    return fact_key in _MECHANICAL_ENTRY_FACTS or (
        fact_key.startswith("character:") and fact_key.endswith(".exists@world")
    ) or (
        fact_key.startswith("character:") and fact_key.endswith(".contact@player")
    ) or (
        fact_key.startswith("scene:") and fact_key.endswith(".exists@world")
    )


def _entry_sources_available(condition, available_facts):
    if not isinstance(condition, dict):
        return False
    if isinstance(condition.get("fact"), str):
        fact_key = condition["fact"]
        return fact_key in available_facts or _is_mechanical_entry_fact(fact_key)
    if "all" in condition:
        return all(
            _entry_sources_available(child, available_facts)
            for child in condition.get("all") or []
        )
    if "any" in condition:
        return any(
            _entry_sources_available(child, available_facts)
            for child in condition.get("any") or []
        )
    if "not" in condition:
        return _entry_sources_available(condition["not"], available_facts)
    return False


def load_preset_blueprints(data_dir):
    """读取 data_dir/quests 下的一层 JSON；一个文件对应一个任务蓝图。"""
    quest_dir = Path(data_dir) / "quests"
    if not quest_dir.is_dir():
        raise ValueError(f"预设任务目录不存在【{quest_dir}】")
    nested_dirs = sorted(path.name for path in quest_dir.iterdir() if path.is_dir())
    if nested_dirs:
        raise ValueError(f"预设任务目录不得包含子目录：{nested_dirs}")
    paths = sorted(quest_dir.glob("*.json"), key=lambda path: path.name)
    if not paths:
        raise ValueError(f"预设任务目录为空【{quest_dir}】")
    return [(path, read_json(path, expected_type=dict)) for path in paths]


def build_initial_preset_state(data_dir, character, explore):
    """构建新档 world_facts、全部隐藏任务及当前可用的 GM 入口提示。"""
    world_facts = empty_world_facts()
    quest_state = empty_quest_state()
    bootstrap_mechanical_facts(world_facts, character, explore)

    loaded = []
    produced_facts = set()
    produced_by_quest = {}
    entry_conditions = {}
    entry_facts = {}
    hook_facts = set()
    for path, raw in load_preset_blueprints(data_dir):
        try:
            normalized = normalize_quest_definition(raw)
            declared = _declared_fact_keys(normalized)
            missing = quest_fact_keys(normalized) - declared
            if missing:
                raise ValueError(f"引用事实未在本任务声明：{sorted(missing)}")
            hook_fact = normalized.get("hook_fact")
            if hook_fact:
                if hook_fact not in declared:
                    raise ValueError(f"由头事实未在本任务声明【{hook_fact}】")
                if hook_fact not in quest_fact_keys(normalized):
                    raise ValueError(f"由头事实未被起始条件引用【{hook_fact}】")
                hook_facts.add(hook_fact)
                produced_facts.add(hook_fact)
            quest_name = normalized["name"]
            entry_conditions[quest_name] = []
            entry_facts[quest_name] = set()
            produced_by_quest[quest_name] = set()
            for node_id in normalized.get("start_nodes") or []:
                condition = normalized["nodes"][node_id].get("condition")
                if condition in (None, {}):
                    raise ValueError(f"起始节点【{node_id}】须提供非空完成条件")
                entry_conditions[quest_name].append(condition)
                entry_facts[quest_name].update(referenced_facts(condition))
            for node in normalized["nodes"].values():
                for mutation in _node_mutations(node):
                    key = _fact_key(mutation)
                    if key:
                        produced_facts.add(key)
                        produced_by_quest[quest_name].add(key)
            definition = create_quest(world_facts, quest_state, raw, hidden=True)
        except ValueError as exc:
            raise ValueError(f"预设任务文件【{path.name}】无效：{exc}") from exc
        loaded.append((path.name, definition["name"]))

    orphaned = {
        name: sorted(
            fact_key for fact_key in facts
            if not _is_mechanical_entry_fact(fact_key) and fact_key not in produced_facts
        )
        for name, facts in entry_facts.items()
    }
    orphaned = {name: facts for name, facts in orphaned.items() if facts}
    if orphaned:
        detail = "；".join(f"{name}: {facts}" for name, facts in sorted(orphaned.items()))
        raise ValueError(f"预设任务存在无来源入口事实：{detail}")

    available_facts = set(_MECHANICAL_ENTRY_FACTS) | hook_facts
    unreachable = set(entry_conditions)
    while unreachable:
        newly_reachable = {
            name for name in unreachable
            if any(
                _entry_sources_available(condition, available_facts)
                for condition in entry_conditions[name]
            )
        }
        if not newly_reachable:
            break
        for name in newly_reachable:
            available_facts.update(produced_by_quest.get(name) or set())
        unreachable -= newly_reachable
    if unreachable:
        detail = "；".join(
            f"{name}: {sorted(entry_facts[name])}" for name in sorted(unreachable)
        )
        raise ValueError(f"预设任务存在不可触发入口链：{detail}")

    hints = potential_progress_hints(world_facts, quest_state)
    return {
        "world_facts": world_facts,
        "quest_state": quest_state,
        "hints": hints,
        "loaded": loaded,
    }
