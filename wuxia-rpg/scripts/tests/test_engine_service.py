#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享 Engine Service HTTP 契约。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SERVICE = os.path.join(SCRIPTS, "engine_service.py")
SKILL_DIR = os.path.dirname(SCRIPTS)
READY_PREFIX = "[engine-service-ready] "


class EngineServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = dict(os.environ)
        env.update({
            "HOST": "127.0.0.1",
            "PORT": "0",
            "WUXIA_RPG_ENGINE_INSTANCE_ID": "python-service-test",
            "WUXIA_RPG_ENGINE_REQUEST_LIMIT": "256",
            "WUXIA_RPG_SAVE_DIR": cls.tmp.name,
            "WUXIA_RPG_SKILL_DIR": SKILL_DIR,
        })
        cls.proc = subprocess.Popen(
            [sys.executable, SERVICE], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8")
        ready = None
        for _ in range(20):
            line = cls.proc.stdout.readline().strip()
            if line.startswith(READY_PREFIX):
                ready = json.loads(line[len(READY_PREFIX):])
                break
            if cls.proc.poll() is not None:
                break
        if ready is None:
            stderr = cls.proc.stderr.read() if cls.proc.stderr else ""
            cls.proc.kill()
            raise RuntimeError(f"engine service 未就绪: {stderr}")
        cls.ready = ready
        cls.base = f"http://127.0.0.1:{ready['port']}"

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            cls.proc.wait(timeout=5)
        cls.tmp.cleanup()

    @classmethod
    def request(cls, method, path, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            cls.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_health_and_tools_discovery(self):
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["service"], "wuxia-rpg-engine")
        self.assertEqual(health["instance_id"], "python-service-test")
        self.assertEqual(health["protocol_version"], "1.0")
        status, manifest = self.request("GET", "/api/tools")
        self.assertEqual(status, 200)
        self.assertEqual(len(manifest["tools"]), 8)

    def test_canonical_and_compatibility_routes_share_gateway(self):
        payload = {"槽位": 0, "类型": "状态", "名称": ["不存在"]}
        status, canonical = self.request("POST", "/api/v1/operations/query", payload)
        self.assertEqual(status, 200)
        status, compatible = self.request("POST", "/api/query", payload)
        self.assertEqual(status, 200)
        self.assertEqual(compatible, canonical)

    def test_unknown_operation_and_request_limit(self):
        status, body = self.request("POST", "/api/v1/operations/shell", {"槽位": 0})
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "unknown_operation")
        status, body = self.request("POST", "/api/v1/operations/query", {
            "槽位": 0, "类型": "角色", "填充": "x" * 300,
        })
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "request_too_large")

    def test_json_read_error_keeps_category(self):
        slot = os.path.join(self.tmp.name, "slot_9")
        os.makedirs(slot, exist_ok=True)
        with open(os.path.join(slot, "explore.json"), "w", encoding="utf-8") as file:
            file.write('{"broken"')

        status, body = self.request(
            "POST", "/api/v1/operations/go", {"槽位": 9, "行为": []})
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "json_syntax_error")


if __name__ == "__main__":
    unittest.main()
