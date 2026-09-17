#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步领域事件触发器注册表。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TriggerOutcome:
    mutations: tuple = ()
    events: tuple = ()


class TriggerRegistry:
    def __init__(self):
        self._subscriptions = []
        self.uses_quest_state = False

    def register(self, event_type, handler):
        self._subscriptions.append(("exact", event_type, handler))
        return handler

    def register_namespace(self, namespace, handler):
        self._subscriptions.append(("namespace", namespace.rstrip("."), handler))
        return handler

    def matching(self, event):
        handlers = []
        for mode, value, handler in self._subscriptions:
            if mode == "exact" and event.is_type(value):
                handlers.append(handler)
            elif mode == "namespace" and event.in_namespace(value):
                handlers.append(handler)
        return handlers


DEFAULT_TRIGGER_REGISTRY = TriggerRegistry()
