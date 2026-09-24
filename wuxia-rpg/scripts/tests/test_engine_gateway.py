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
    "wuxia_plot_writing": "plot-writing",
    "wuxia_check": "check",
    "wuxia_random_event": "random-event",
    "wuxia_scene_prepare": "scene-prepare",
    "wuxia_quest_prepare": "quest-prepare",
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

    def plot_writing(slot, payload):
        calls.append(("plot-writing", payload))
        return {"operation": "plot-writing", "槽位": slot}

    return SimpleNamespace(
        go=go,
        judge=judge,
        plot_writing=plot_writing,
        check=record("check"),
        random_event=record("random-event"),
        scene_prepare=record("scene-prepare"),
        quest_prepare=record("quest-prepare"),
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
        self.assertEqual(manifest["protocol_version"], "1.9")

    def test_gateway_implements_every_declared_operation(self):
        gateway = EngineGateway(engine_module=fake_engine([]))
        self.assertEqual(set(gateway.operations), set(EXPECTED.values()))

    def test_go_schema_allows_empty_action_placeholder(self):
        manifest = load_tools_manifest()
        tool = next(item for item in manifest["tools"] if item["name"] == "wuxia_go")
        actions = tool["input_schema"]["properties"]["行为"]
        self.assertNotIn("minItems", actions)
        self.assertIn("空数组", actions["description"])

    def test_plot_writing_and_judge_schemas_split_narrative(self):
        tools = {item["operation"]: item["input_schema"]
                 for item in load_tools_manifest()["tools"]}
        self.assertEqual(tools["judge"]["required"], ["槽位"])
        self.assertNotIn("场景要素", tools["judge"]["properties"])
        self.assertEqual(set(tools["plot-writing"]["required"]),
                         {"槽位", "当前剧情", "场景要素", "提及地点"})
        self.assertNotIn("行为", tools["plot-writing"]["required"])
        self.assertEqual(tools["plot-writing"]["properties"]["场景要素"]["minItems"], 1)
        self.assertEqual(tools["scene-prepare"]["properties"]["场景"]["minItems"], 1)
        self.assertNotIn("turn-reset", tools)

    def test_quest_prepare_schema_supports_all_engine_operations(self):
        tools = {item["operation"]: item["input_schema"]
                 for item in load_tools_manifest()["tools"]}
        quest_item = tools["quest-prepare"]["properties"]["任务"]["items"]
        self.assertEqual(quest_item["properties"]["操作"]["enum"],
                         ["创建", "扩展", "修改", "关闭"])
        self.assertEqual(set(quest_item["required"]), {"操作", "蓝图"})


class EngineGatewayTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.gateway = EngineGateway(
            engine_module=fake_engine(self.calls), lock=threading.Lock())

    def test_dispatches_all_operations(self):
        payloads = {
            "go": {"槽位": 1, "行为": []},
            "judge": {"槽位": 1},
            "plot-writing": {"槽位": 1, "当前剧情": "测试", "场景要素": [{}], "提及地点": []},
            "check": {"槽位": 1},
            "random-event": {"槽位": 1},
            "scene-prepare": {"槽位": 1, "场景": [
                {"操作": "隔离", "区域": "苏州", "场景": "废园"},
            ]},
            "quest-prepare": {"槽位": 1, "任务": [{"操作": "创建", "蓝图": {}}]},
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

    def test_go_requires_actions_but_judge_accepts_slot_only(self):
        with self.assertRaisesRegex(GatewayProtocolError, "行为（数组）"):
            self.gateway.invoke("go", {"槽位": 1})
        self.gateway.invoke("judge", {"槽位": 1})
        self.gateway.invoke("judge", {"槽位": 1, "行为": [{"类型": "战斗-开始"}],
                                      "当前剧情": "战况"})
        with self.assertRaisesRegex(GatewayProtocolError, "行为须为数组"):
            self.gateway.invoke("judge", {"槽位": 1, "行为": {}})
        with self.assertRaisesRegex(GatewayProtocolError, "当前剧情仅限战斗"):
            self.gateway.invoke("judge", {"槽位": 1, "当前剧情": "剧情"})
        with self.assertRaisesRegex(GatewayProtocolError, "仅允许"):
            self.gateway.invoke("judge", {"槽位": 1, "场景要素": []})

    def test_plot_writing_requires_narrative_and_optional_action_array(self):
        narrative = {"槽位": 1, "当前剧情": "剧情", "场景要素": [{}], "提及地点": []}
        self.gateway.invoke("plot-writing", narrative)
        self.gateway.invoke("plot-writing", {**narrative, "行为": []})
        for changes, message in [
            ({"当前剧情": ""}, "当前剧情"),
            ({"场景要素": []}, "场景要素"),
            ({"提及地点": None}, "提及地点"),
            ({"行为": {}}, "行为"),
        ]:
            with self.subTest(changes=changes), self.assertRaisesRegex(
                    GatewayProtocolError, message):
                self.gateway.invoke("plot-writing", {**narrative, **changes})

    def test_turn_reset_is_not_public(self):
        with self.assertRaises(GatewayProtocolError) as ctx:
            self.gateway.invoke("turn-reset", {"槽位": 1})
        self.assertEqual(ctx.exception.code, "unknown_operation")

    def test_scene_prepare_requires_array_items_and_positive_slot(self):
        with self.assertRaisesRegex(GatewayProtocolError, "正整数"):
            self.gateway.invoke("scene-prepare", {"槽位": 0, "场景": []})
        with self.assertRaisesRegex(GatewayProtocolError, "非空数组"):
            self.gateway.invoke("scene-prepare", {"槽位": 1})
        with self.assertRaisesRegex(GatewayProtocolError, "非空数组"):
            self.gateway.invoke("scene-prepare", {"槽位": 1, "场景": []})
        with self.assertRaisesRegex(GatewayProtocolError, "第 1 项须为对象"):
            self.gateway.invoke("scene-prepare", {"槽位": 1, "场景": ["bad"]})
        with self.assertRaisesRegex(GatewayProtocolError, "操作须为"):
            self.gateway.invoke("scene-prepare", {"槽位": 1, "场景": [{}]})

    def test_quest_prepare_requires_batch_items_and_positive_slot(self):
        with self.assertRaisesRegex(GatewayProtocolError, "正整数"):
            self.gateway.invoke("quest-prepare", {"槽位": 0, "任务": []})
        with self.assertRaisesRegex(GatewayProtocolError, "非空数组"):
            self.gateway.invoke("quest-prepare", {"槽位": 1})
        with self.assertRaisesRegex(GatewayProtocolError, "第 1 项须为对象"):
            self.gateway.invoke("quest-prepare", {"槽位": 1, "任务": ["bad"]})
        with self.assertRaisesRegex(GatewayProtocolError, "操作须为"):
            self.gateway.invoke("quest-prepare", {"槽位": 1, "任务": [{}]})
        with self.assertRaisesRegex(GatewayProtocolError, "蓝图（对象）"):
            self.gateway.invoke("quest-prepare", {
                "槽位": 1, "任务": [{"操作": "创建"}],
            })
        for operation in ("修改", "关闭"):
            with self.subTest(operation=operation):
                self.gateway.invoke("quest-prepare", {
                    "槽位": 1, "任务": [{"操作": operation,
                                         "蓝图": {"名称": "线索", "描述": "结束"}}],
                })
        with self.assertRaisesRegex(GatewayProtocolError, "关闭蓝图须含非空"):
            self.gateway.invoke("quest-prepare", {
                "槽位": 1, "任务": [{"操作": "关闭", "蓝图": {"名称": "线索"}}],
            })

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
