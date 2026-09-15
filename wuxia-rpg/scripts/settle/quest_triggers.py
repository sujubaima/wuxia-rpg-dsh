#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机械事件→规范事实、事实→任务归约及 GM 候选提示。"""
from settle.domain_events import (CHARACTER_CREATED, COPPER_CHANGED, DEATH_CHANGED,
                                  FACT_CHANGED, HP_CHANGED, ITEM_CHANGED,
                                  LOCATION_CHANGED, MP_CHANGED, PARTY_CHANGED,
                                  PLAYER_ACTION_COMPLETED, QUEST_CREATED,
                                  QUEST_DISCOVERED, QUEST_EXTENDED,
                                  RELATION_CHANGED, SKILL_CHANGED,
                                  STAMINA_CHANGED, TIME_ADVANCED)
from settle.quest_engine import potential_progress_hints, reduce_affected_quests
from settle.triggers import TriggerOutcome, TriggerRegistry


def _segment(value):
    return str(value).replace("@", ":").replace(".", ":")


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
        return (_fact_mutation(f"{subject}.location@world", after, "string"),)
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
    return ()


def _mechanical_handler(event, session):
    mutations = _mechanical_fact_mutations(event)
    return TriggerOutcome(mutations=mutations) if mutations else None


def _reduce_handler(event, session):
    quest_event = event.type in (QUEST_CREATED, QUEST_DISCOVERED, QUEST_EXTENDED)
    quest_id = event.get("quest_id") if quest_event else None
    fact_key = event.get("fact_key") if event.is_type(FACT_CHANGED) else None
    public_notice = None
    if quest_id:
        definition = session.quest_state.get("definitions", {}).get(quest_id) or {}
        runtime = session.quest_state.get("runtimes", {}).get(quest_id) or {}
        if runtime.get("lifecycle") != "hidden":
            kind = "updated" if event.is_type(QUEST_EXTENDED) else "discovered"
            public_notice = {
                "quest_id": quest_id,
                "quest_name": definition.get("name") or quest_id,
                "kind": kind,
            }
    mutations, events, notices, hints = reduce_affected_quests(
        session.world_facts, session.quest_state, fact_key=fact_key, quest_id=quest_id,
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
