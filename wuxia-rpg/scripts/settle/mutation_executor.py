#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 mutation 注册、应用与领域事件投影。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MutationContext:
    slot: int
    explore: dict
    event_factory: object
    session: object = None


@dataclass(frozen=True)
class MutationSpec:
    apply: object
    snapshot: object = None
    project: object = None


@dataclass(frozen=True)
class MutationExecution:
    results: tuple
    events: tuple


class MutationExecutor:
    def __init__(self):
        self._registry = {}

    def register(self, kind, apply, snapshot=None, project=None):
        if not isinstance(kind, str) or not kind:
            raise ValueError("mutation kind 必须为非空字符串")
        if kind in self._registry:
            raise ValueError(f"mutation kind 重复注册【{kind}】")
        self._registry[kind] = MutationSpec(apply, snapshot, project)
        return self

    def execute(self, context, mutation):
        if not isinstance(mutation, dict):
            return MutationExecution((self._failure("非法状态变更条目"),), ())
        # 任务奖励/效果携带 _来源 标（任务/节点/类别）：执行前剥离，失败时回填到结果，
        # 使打回信息能定位到具体任务与节点（GM 由此知悉用 quest-prepare「修改」修正）。
        origin = mutation.get("_来源")
        if origin is not None:
            mutation = {key: value for key, value in mutation.items() if key != "_来源"}
        kind = mutation.get("类型")
        spec = self._registry.get(kind)
        if spec is None:
            return MutationExecution(
                (self._with_origin(self._failure(f"未知状态变更类型【{kind}】"), origin),), ())
        try:
            before = spec.snapshot(context, mutation) if spec.snapshot else None
            raw = spec.apply(context, mutation)
            results = raw if isinstance(raw, list) else [raw]
            normalized = []
            for result in results:
                if not isinstance(result, dict):
                    result = {"ok": False, "msg": "mutation handler 返回值非法"}
                if not result.get("ok"):
                    result["_结算错误"] = True
                normalized.append(self._with_origin(result, origin))
            events = []
            if normalized and all(r.get("ok") for r in normalized) and spec.project:
                after = spec.snapshot(context, mutation) if spec.snapshot else None
                events = list(spec.project(context, mutation, before, after, normalized) or [])
            return MutationExecution(tuple(normalized), tuple(events))
        except (KeyError, TypeError, ValueError) as exc:
            return MutationExecution((self._with_origin(self._failure(str(exc)), origin),), ())

    @staticmethod
    def _with_origin(result, origin):
        if origin is None or result.get("ok"):
            return result
        result = dict(result)
        label = f"任务【{origin.get('任务')}】节点【{origin.get('节点')}】{origin.get('类别', '奖励')}"
        if origin.get("奖励ID"):
            label += f"【{origin.get('奖励ID')}】"
        result["msg"] = f"{label}执行失败：{result.get('msg')}"
        if origin.get("类别") == "奖励":
            result["msg"] += "；请在 quest-prepare 用「修改」操作修正该节点奖励后重新提交"
        result["_来源"] = origin
        return result

    def execute_batch(self, context, mutations):
        results = []
        events = []
        for mutation in mutations:
            execution = self.execute(context, mutation)
            results.extend(execution.results)
            events.extend(execution.events)
        if not all(r.get("ok") for r in results):
            events = []
        return MutationExecution(tuple(results), tuple(events))

    @staticmethod
    def _failure(message):
        return {"ok": False, "msg": message, "_结算错误": True}
