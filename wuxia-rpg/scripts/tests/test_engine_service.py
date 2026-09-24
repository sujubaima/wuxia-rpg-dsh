#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享 Engine Service HTTP 契约。"""

from concurrent.futures import ThreadPoolExecutor
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
        self.assertEqual(health["protocol_version"], "1.9")
        status, manifest = self.request("GET", "/api/tools")
        self.assertEqual(status, 200)
        self.assertEqual(len(manifest["tools"]), 11)
        operations = {tool["operation"] for tool in manifest["tools"]}
        self.assertIn("plot-writing", operations)
        self.assertNotIn("turn-reset", operations)

    def test_canonical_and_compatibility_routes_share_gateway(self):
        payload = {"槽位": 0, "类型": "状态", "名称": ["不存在"]}
        status, canonical = self.request("POST", "/api/v1/operations/query", payload)
        self.assertEqual(status, 200)
        status, compatible = self.request("POST", "/api/query", payload)
        self.assertEqual(status, 200)
        self.assertEqual(compatible, canonical)

        scene_payload = {"槽位": 1, "场景": [
            {"操作": "隔离", "区域": "苏州", "场景": "废园"},
        ]}
        status, canonical = self.request(
            "POST", "/api/v1/operations/scene-prepare", scene_payload)
        self.assertEqual(status, 200)
        status, compatible = self.request("POST", "/api/scene-prepare", scene_payload)
        self.assertEqual(status, 200)
        self.assertEqual(compatible, canonical)

        draft_payload = {"槽位": 1, "任务": [{"操作": "创建", "蓝图": {}}]}
        status, canonical = self.request(
            "POST", "/api/v1/operations/quest-prepare", draft_payload)
        self.assertEqual(status, 200)
        status, compatible = self.request("POST", "/api/quest-prepare", draft_payload)
        self.assertEqual(status, 200)
        self.assertEqual(compatible, canonical)

        operation = "plot-writing"
        payload = {"槽位": 0, "当前剧情": "剧情",
                   "场景要素": [{}], "提及地点": []}
        status, canonical = self.request(
            "POST", f"/api/v1/operations/{operation}", payload)
        self.assertEqual(status, 200)
        status, compatible = self.request("POST", f"/api/{operation}", payload)
        self.assertEqual(status, 200)
        self.assertEqual(compatible, canonical)

    def test_new_operation_input_errors_are_protocol_errors(self):
        for operation, payload in (
            ("plot-writing", {"槽位": 1, "场景要素": [{}], "提及地点": []}),
            ("plot-writing", {"槽位": 1, "当前剧情": "剧情",
                              "场景要素": [], "提及地点": []}),
            ("scene-prepare", {"槽位": 1, "场景": []}),
            ("judge", {"槽位": 1, "行为": {}}),
        ):
            with self.subTest(operation=operation, payload=payload):
                status, body = self.request(
                    "POST", f"/api/v1/operations/{operation}", payload)
                self.assertEqual(status, 400)
                self.assertEqual(body["code"], "invalid_request")

    def test_unknown_operation_and_request_limit(self):
        for operation in ("shell", "turn-reset"):
            status, body = self.request(
                "POST", f"/api/v1/operations/{operation}", {"槽位": 0})
            self.assertEqual(status, 404)
            self.assertEqual(body["code"], "unknown_operation")
        status, body = self.request("POST", "/api/turn-reset", {"槽位": 0})
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "not_found")
        status, body = self.request("POST", "/api/v1/operations/query", {
            "槽位": 0, "类型": "角色", "填充": "x" * 300,
        })
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "request_too_large")

    def test_http_and_cli_go_share_cross_process_slot_lock(self):
        if SCRIPTS not in sys.path:
            sys.path.insert(0, SCRIPTS)
        from store import save_manager as sm, turn_workspace as ws
        from tests.test_slot_allocation import character

        slot = 8
        sm.create_slot(character("并发测试客"), slot, self.tmp.name)
        payload = {"槽位": slot, "行为": [{"类型": "交谈观察", "目标": "周遭"}]}

        def cli_go():
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "engine.py"), "go"],
                input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                text=True, timeout=30,
                env={**os.environ, "WUXIA_RPG_SAVE_DIR": self.tmp.name})
            self.assertIn(proc.returncode, (0, 2), proc.stderr)
            return json.loads(proc.stdout)

        with ThreadPoolExecutor(max_workers=2) as workers:
            with ws.slot_lock(slot, self.tmp.name):
                http = workers.submit(self.request, "POST", "/api/v1/operations/go", payload)
                cli = workers.submit(cli_go)
                self.assertFalse(http.done())
                self.assertFalse(cli.done())
            status, http_result = http.result(timeout=30)
            cli_result = cli.result(timeout=30)
        self.assertEqual(status, 200)
        results = [http_result, cli_result]
        self.assertEqual(sum(r.get("turn_state") == "AWAITING_PLOT" and "错误" not in r
                             for r in results), 1, results)
        self.assertEqual(sum(r.get("状态冲突") == "go_already_staged" for r in results), 1,
                         results)
        self.assertTrue(ws.pending_exists(slot, self.tmp.name))

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
