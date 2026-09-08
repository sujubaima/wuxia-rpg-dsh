#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web EngineClient 与最小权限工具集。"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB = os.path.join(ROOT, "web")
AGENT = os.path.join(ROOT, "agent")
SKILL = os.path.join(ROOT, "wuxia-rpg")
for path in (WEB, AGENT):
    if path not in sys.path:
        sys.path.insert(0, path)

from core import Agent
from engine_client import EngineClient
from wuxia_tools import WEB_SKILL_USAGE_NOTE, build_wuxia_registry


class FakeClient:
    def __init__(self):
        self.calls = []

    def call_operation(self, operation, payload):
        self.calls.append((operation, payload))
        return {"operation": operation, "payload": payload}


class WuxiaToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(SKILL, "tools.json"), encoding="utf-8") as f:
            cls.manifest = json.load(f)

    def setUp(self):
        self.client = FakeClient()
        self.registry = build_wuxia_registry(self.client, self.manifest, SKILL)

    def test_registry_contains_only_engine_and_reference_tools(self):
        expected = {tool["name"] for tool in self.manifest["tools"]}
        expected.add("wuxia_read_reference")
        self.assertEqual(set(self.registry.names()), expected)
        self.assertTrue({"read", "write", "bash", "list"}.isdisjoint(self.registry.names()))

    def test_engine_tool_uses_manifest_operation(self):
        result = json.loads(self.registry.execute(
            "wuxia_setting", json.dumps({"槽位": 0, "目标": "武当派"}, ensure_ascii=False)))
        self.assertEqual(result["operation"], "setting")
        self.assertEqual(self.client.calls, [("setting", {"槽位": 0, "目标": "武当派"})])

    def test_reference_reader_stays_under_references(self):
        ok = json.loads(self.registry.execute(
            "wuxia_read_reference", json.dumps({"path": "references/wuxia-rpg-actions.md"})))
        self.assertIn("content", ok)
        escaped = json.loads(self.registry.execute(
            "wuxia_read_reference", json.dumps({"path": "../SKILL.md"})))
        self.assertIn("错误", escaped)
        script = json.loads(self.registry.execute(
            "wuxia_read_reference", json.dumps({"path": "../scripts/engine.py"})))
        self.assertIn("错误", script)

    def test_agent_uses_host_specific_skill_guidance(self):
        agent = Agent(
            client=object(), tools=self.registry, skill_dirs=[SKILL],
            skill_usage_note=WEB_SKILL_USAGE_NOTE)
        result = json.loads(agent.tools.execute(
            "use_skill", json.dumps({"name": "wuxia-rpg"})))
        self.assertIn("wuxia_read_reference", result["instructions"])
        self.assertNotIn("用 bash", result["instructions"])
        self.assertIn("use_skill", agent.tools.names())


class EngineClientProcessTest(unittest.TestCase):
    def test_starts_shared_service_and_calls_operation(self):
        with tempfile.TemporaryDirectory() as save_dir, patch.dict(os.environ, {
            "WUXIA_RPG_SAVE_DIR": save_dir,
            "WUXIA_RPG_RENDER_MODULE": "WEB_UI",
        }):
            client = EngineClient.connect(SKILL, startup_timeout=10)
            try:
                manifest = client.get_tools()
                self.assertEqual(manifest["protocol_version"], "1.0")
                result = client.call_operation("query", {
                    "槽位": 0, "类型": "状态", "名称": ["不存在"],
                })
                self.assertIsInstance(result, dict)
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
