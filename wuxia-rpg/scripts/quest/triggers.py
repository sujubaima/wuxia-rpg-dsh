#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机械事件→规范事实、事实→任务归约及 GM 候选提示。"""
from quest.events import (CHARACTER_CREATED, COPPER_CHANGED, DEATH_CHANGED,
                                  FACT_CHANGED, HP_CHANGED, ITEM_CHANGED,
                                  LOCATION_CHANGED, MP_CHANGED, NPC_CONTACTED,
                                  PARTY_CHANGED, PLAYER_ACTION_COMPLETED,
                                  QUEST_CREATED, QUEST_DISCOVERED,
                                  QUEST_EXTENDED, RELATION_CHANGED, SKILL_CHANGED,
                                  STAMINA_CHANGED, TIME_ADVANCED)
from quest.engine import potential_progress_hints, reduce_affected_quests
from quest.registry import TriggerOutcome, TriggerRegistry
from quest.world_facts import upsert_fact


def _segment(value):
    return str(value).replace("@", ":").replace(".", ":")


def _region(value):
    return str(value).split("·", 1)[0].strip() if value is not None else ""


def _fact_mutation(fact_key, value, value_type, allowed_values=None):
    definition = {"事实键": fact_key, "值类型": value_type, "修订策略": "free"}
    if allowed_values is not None:
        definition["可选值"] = allowed_values
    return {
        "类型": "事实-写入", "事实": fact_key, "值": value,
        "状态": "verified", "_内部": True, "_定义": definition,
    }


def _mechanical_fact_mutations(event):
    after = event.get("after")
    character = event.get("character")
    if event.is_type(STAMINA_CHANGED):
        return (_fact_mutation("party.stamina@world", after, "number"),)
    if event.is_type(TIME_ADVANCED):
        return (_fact_mutation("world.time@world", after, "number"),)
    if event.is_type(COPPER_CHANGED) and character:
        return (_fact_mutation(f"character:{_segment(character)}.copper@world", after, "number"),)
    if event.is_type(HP_CHANGED) and character:
        return (_fact_mutation(f"character:{_segment(character)}.hp@world", after, "number"),)
    if event.is_type(MP_CHANGED) and character:
        return (_fact_mutation(f"character:{_segment(character)}.mp@world", after, "number"),)
    if event.is_type(RELATION_CHANGED) and character:
        return (_fact_mutation(f"character:{_segment(character)}.relation@player", after, "number"),)
    if event.is_type(PARTY_CHANGED) and character:
        return (_fact_mutation(f"character:{_segment(character)}.in_party@world", bool(after), "bool"),)
    if event.is_type(DEATH_CHANGED) and character:
        return (_fact_mutation(f"character:{_segment(character)}.dead@world", bool(after), "bool"),)
    if event.is_type(LOCATION_CHANGED):
        if after is None:
            return ()
        subject = f"character:{_segment(character)}" if character else "player"
        mutations = [_fact_mutation(f"{subject}.location@world", after, "string")]
        if not character and _region(after):
            mutations.append(_fact_mutation("player.region@world", _region(after), "string"))
        return tuple(mutations)
    if event.is_type(ITEM_CHANGED) and character and event.get("item"):
        key = f"character:{_segment(character)}.item:{_segment(event.get('item'))}:quantity@world"
        return (_fact_mutation(key, after, "number"),)
    if event.is_type(SKILL_CHANGED) and character and event.get("skill"):
        prefix = f"character:{_segment(character)}.skill:{_segment(event.get('skill'))}"
        mutations = [_fact_mutation(f"{prefix}:known@world", after is not None, "bool")]
        if after is not None:
            mutations.append(_fact_mutation(f"{prefix}:level@world", after, "number"))
        return tuple(mutations)
    if event.is_type(CHARACTER_CREATED) and character:
        return (_fact_mutation(f"character:{_segment(character)}.exists@world", True, "bool"),)
    if event.is_type(NPC_CONTACTED) and character:
        return (_fact_mutation(f"character:{_segment(character)}.contact@player", True, "bool"),)
    return ()


def bootstrap_mechanical_facts(world_facts, character, explore):
    """写入新档已经成立、但不会经过普通领域事件的基础机械事实。"""
    name = (character or {}).get("名称")
    mutations = [
        _fact_mutation("player.region@world", _region((explore or {}).get("当前位置")), "string"),
        _fact_mutation("world.time@world", int((explore or {}).get("当前时间", 0) or 0), "number"),
        _fact_mutation("party.stamina@world", int((explore or {}).get("体力", 0) or 0), "number"),
    ]
    if name:
        mutations.append(
            _fact_mutation(f"character:{_segment(name)}.exists@world", True, "bool")
        )
    for mutation in mutations:
        if mutation["值"] in (None, ""):
            continue
        upsert_fact(
            world_facts,
            mutation["事实"],
            mutation["值"],
            status=mutation["状态"],
            source="system",
            definition=mutation["_定义"],
        )
    return world_facts


def _mechanical_handler(event, session):
    mutations = _mechanical_fact_mutations(event)
    return TriggerOutcome(mutations=mutations) if mutations else None


def _reduce_handler(event, session):
    quest_event = event.type in (QUEST_CREATED, QUEST_DISCOVERED, QUEST_EXTENDED)
    quest_name = event.get("quest_name") if quest_event else None
    fact_key = event.get("fact_key") if event.is_type(FACT_CHANGED) else None
    # 线索扩展是 GM 内部行为，不向玩家广播；只有 创建/发现 与节点结算对外可见
    public_notice = None
    if quest_name and event.type in (QUEST_CREATED, QUEST_DISCOVERED):
        runtime = session.quest_state.get("runtimes", {}).get(quest_name) or {}
        if runtime.get("lifecycle") != "hidden":
            public_notice = {
                "quest_name": quest_name,
                "kind": "discovered",
            }
    mutations, events, notices, hints = reduce_affected_quests(
        session.world_facts, session.quest_state, fact_key=fact_key, quest_name=quest_name,
    )
    if events or notices or mutations:
        session.mark_quest_state_dirty()
    if public_notice:
        session.add_notices((public_notice,))
    session.add_notices(notices)
    session.add_hints(hints)
    if not mutations and not events:
        return None
    return TriggerOutcome(mutations=tuple(mutations), events=tuple(events))


def _potential_handler(event, session):
    session.add_hints(potential_progress_hints(session.world_facts, session.quest_state))
    return None


def build_quest_trigger_registry():
    registry = TriggerRegistry()
    registry.uses_quest_state = True
    registry.register_namespace("state", _mechanical_handler)
    registry.register(FACT_CHANGED, _reduce_handler)
    registry.register(QUEST_CREATED, _reduce_handler)
    registry.register(QUEST_DISCOVERED, _reduce_handler)
    registry.register(QUEST_EXTENDED, _reduce_handler)
    registry.register(PLAYER_ACTION_COMPLETED, _potential_handler)
    return registry
