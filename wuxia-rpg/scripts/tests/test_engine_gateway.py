#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一 Tools Schema 与 EngineGateway 契约。"""

import os
import sys
import threading
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from common.json_io import JsonSyntaxError
from engine_gateway import EngineGateway, GatewayError, GatewayProtocolError, load_tools_manifest


EXPECTED = {
    "wuxia_go": "go",
    "wuxia_judge": "judge",
    "wuxia_check": "check",
    "wuxia_random_event": "random-event",
    "wuxia_query": "query",
    "wuxia_setting": "setting",
    "wuxia_recommend": "recommend",
    "wuxia_map_query": "map-query",
}


def fake_engine(calls):
    def record(name):
        def handler(payload):
            calls.append((name, payload))
            return {"operation": name}
        return handler

    def go(slot, actions):
        calls.append(("go", {"槽位": slot, "行为": actions}))
        return {"operation": "go"}

    def judge(slot, payload):
        calls.append(("judge", payload))
        return {"operation": "judge", "槽位": slot}

    return SimpleNamespace(
        go=go,
        judge=judge,
        check=record("check"),
        random_event=record("random-event"),
        query=record("query"),
        setting=record("setting"),
        recommend=record("recommend"),
        map_query=record("map-query"),
    )


class ToolsManifestContractTest(unittest.TestCase):
    def test_manifest_declares_exact_public_tools(self):
        manifest = load_tools_manifest()
        declared = {tool["name"]: tool["operation"] for tool in manifest["tools"]}
        self.assertEqual(declared, EXPECTED)
        self.assertEqual(manifest["protocol_version"], "1.0")

    def test_gateway_implements_every_declared_operation(self):
        gateway = EngineGateway(engine_module=fake_engine([]))
        self.assertEqual(set(gateway.operations), set(EXPECTED.values()))


class EngineGatewayTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.gateway = EngineGateway(
            engine_module=fake_engine(self.calls), lock=threading.Lock())

    def test_dispatches_all_operations(self):
        payloads = {
            "go": {"槽位": 1, "行为": []},
            "judge": {"槽位": 1, "行为": [], "当前剧情": "测试"},
            "check": {"槽位": 1},
            "random-event": {"槽位": 1},
            "query": {"槽位": 0, "类型": "角色"},
            "setting": {"槽位": 0, "目标": "武当派"},
            "recommend": {"槽位": 0, "一级属性": {}, "武学偏好": "剑法"},
            "map-query": {"槽位": 0, "区域": "配额"},
        }
        for operation, payload in payloads.items():
            with self.subTest(operation=operation):
                result = self.gateway.invoke(operation, payload)
                self.assertEqual(result["operation"], operation)
        self.assertEqual([name for name, _ in self.calls], list(payloads))

    def test_rejects_unknown_operation(self):
        with self.assertRaises(GatewayProtocolError) as ctx:
            self.gateway.invoke("shell", {"槽位": 1})
        self.assertEqual(ctx.exception.code, "unknown_operation")
        self.assertEqual(ctx.exception.status, 404)

    def test_rejects_non_object_payload_and_invalid_slot(self):
        with self.assertRaisesRegex(GatewayProtocolError, "JSON 对象"):
            self.gateway.invoke("query", [])
        with self.assertRaisesRegex(GatewayProtocolError, "有效 槽位"):
            self.gateway.invoke("query", {"槽位": True})

    def test_go_and_judge_require_action_arrays(self):
        with self.assertRaisesRegex(GatewayProtocolError, "行为（数组）"):
            self.gateway.invoke("go", {"槽位": 1})
        with self.assertRaisesRegex(GatewayProtocolError, "行为（数组）"):
            self.gateway.invoke("judge", {"槽位": 1, "行为": {}})

    def test_preserves_json_read_error_code(self):
        def broken_query(_payload):
            raise JsonSyntaxError("explore.json", "测试损坏")

        engine = fake_engine([])
        engine.query = broken_query
        gateway = EngineGateway(engine_module=engine, lock=threading.Lock())
        with self.assertRaises(GatewayError) as ctx:
            gateway.invoke("query", {"槽位": 1})
        self.assertEqual(ctx.exception.code, "json_syntax_error")
        self.assertEqual(ctx.exception.status, 500)


if __name__ == "__main__":
    unittest.main()
