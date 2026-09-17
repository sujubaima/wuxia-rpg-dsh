#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结算领域事件的内部模型与协议边界。"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


STAMINA_CHANGED = "state.stamina.changed"
TIME_ADVANCED = "state.time.advanced"
COPPER_CHANGED = "state.copper.changed"
ITEM_CHANGED = "state.item.changed"
LOCATION_CHANGED = "state.location.changed"
RELATION_CHANGED = "state.relation.changed"
PARTY_CHANGED = "state.party.changed"
DEATH_CHANGED = "state.death.changed"
SKILL_CHANGED = "state.skill.changed"
HP_CHANGED = "state.hp.changed"
MP_CHANGED = "state.mp.changed"
EQUIPMENT_CHANGED = "state.equipment.changed"
LOADOUT_CHANGED = "state.loadout.changed"
CHARACTER_CREATED = "state.character.created"
NPC_CONTACTED = "state.character.contacted"
BATTLE_ENDED = "battle.ended"
PLAYER_ACTION_COMPLETED = "action.player.completed"
NARRATIVE_EVENT = "narrative.occurred"
FACT_CHANGED = "world.fact.changed"
QUEST_CREATED = "quest.created"
QUEST_EXTENDED = "quest.extended"
QUEST_DISCOVERED = "quest.discovered"
QUEST_NODE_COMPLETED = "quest.node.completed"
QUEST_NODE_CLOSED = "quest.node.closed"
QUEST_NODE_BLOCKED = "quest.node.blocked"
QUEST_LIFECYCLE_CHANGED = "quest.lifecycle.changed"


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class EventRequest:
    """触发器请求发出的事件；正式 envelope 仍由 EventFactory 统一构造。"""

    type: str
    payload: Mapping[str, Any]
    origin: str = "trigger"


@dataclass(frozen=True)
class DomainEvent:
    """内部稳定事件视图；消费者不依赖序列化字典布局。"""

    type: str
    payload: Mapping[str, Any]
    origin: str
    slot: int
    sequence: int

    def is_type(self, event_type):
        return self.type == event_type

    def in_namespace(self, namespace):
        prefix = namespace.rstrip(".") + "."
        return self.type == namespace.rstrip(".") or self.type.startswith(prefix)

    def get(self, key, default=None):
        return self.payload.get(key, default)

    def payload_dict(self):
        return _thaw(self.payload)


class EventFactory:
    """为一次 settlement 生成有序事件，隔离 envelope 默认字段。"""

    def __init__(self, slot, origin):
        self.slot = int(slot)
        self.origin = str(origin)
        self._sequence = 0

    def create(self, event_type, payload=None, origin=None):
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("领域事件 type 必须为非空字符串")
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ValueError("领域事件 payload 必须为对象")
        self._sequence += 1
        return DomainEvent(
            type=event_type.strip(),
            payload=_freeze(payload),
            origin=str(origin or self.origin),
            slot=self.slot,
            sequence=self._sequence,
        )

    def from_request(self, request):
        if not isinstance(request, EventRequest):
            raise TypeError("trigger event 必须为 EventRequest")
        return self.create(request.type, request.payload, request.origin)


class EventCodecV1:
    """可替换的 V1 序列化边界；当前只用于测试/诊断，不写入存档。"""

    VERSION = 1

    @classmethod
    def encode(cls, event):
        if not isinstance(event, DomainEvent):
            raise TypeError("只可编码 DomainEvent")
        return {
            "version": cls.VERSION,
            "type": event.type,
            "payload": event.payload_dict(),
            "origin": event.origin,
            "slot": event.slot,
            "sequence": event.sequence,
        }

    @classmethod
    def decode(cls, data):
        if not isinstance(data, Mapping):
            raise ValueError("事件协议须为对象")
        if data.get("version") != cls.VERSION:
            raise ValueError(f"不支持的事件协议版本【{data.get('version')}】")
        event_type = data.get("type")
        payload = data.get("payload", {})
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("事件协议缺 type")
        if not isinstance(payload, Mapping):
            raise ValueError("事件协议 payload 须为对象")
        return DomainEvent(
            type=event_type.strip(),
            payload=_freeze(payload),
            origin=str(data.get("origin") or "unknown"),
            slot=int(data.get("slot", 0)),
            sequence=int(data.get("sequence", 0)),
        )
