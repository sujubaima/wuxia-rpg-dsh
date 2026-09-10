#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 会话池、限流器与 JSON 请求边界。"""

import http.client
import io
import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import server  # noqa: E402
from resource_limits import (  # noqa: E402
    AgentSessionPool,
    RequestLimitError,
    SessionBusyError,
    SessionCapacityError,
    SlidingWindowLimiter,
    read_json_object,
)


class FakeConnection:
    def __init__(self):
        self.timeout = None

    def gettimeout(self):
        return self.timeout

    def settimeout(self, timeout):
        self.timeout = timeout


class TimeoutReader:
    def read(self, _length):
        raise socket.timeout()


class RequestReaderTest(unittest.TestCase):
    def read(self, body, **overrides):
        raw = body.encode("utf-8")
        options = {
            "max_bytes": 1024,
            "max_depth": 4,
            "timeout_seconds": 1,
        }
        options.update(overrides)
        return read_json_object(
            io.BytesIO(raw), {"Content-Length": str(len(raw))}, FakeConnection(),
            **options,
        )

    def test_reads_utf8_json_object(self):
        self.assertEqual(self.read('{"message":"你好"}'), {"message": "你好"})

    def test_rejects_missing_length_and_oversized_body(self):
        with self.assertRaisesRegex(RequestLimitError, "Content-Length") as caught:
            read_json_object(io.BytesIO(), {}, FakeConnection(),
                             max_bytes=10, max_depth=4, timeout_seconds=1)
        self.assertEqual(caught.exception.status, 411)

        with self.assertRaises(RequestLimitError) as caught:
            self.read('{"message":"too long"}', max_bytes=4)
        self.assertEqual(caught.exception.status, 413)

    def test_rejects_non_object_and_excessive_depth(self):
        with self.assertRaises(RequestLimitError) as caught:
            self.read("[]")
        self.assertEqual(caught.exception.status, 400)

        self.assertEqual(self.read('{"a":1}', max_depth=1), {"a": 1})
        with self.assertRaisesRegex(RequestLimitError, "嵌套过深"):
            self.read('{"a":{"b":{"c":1}}}', max_depth=2)

        deeply_nested = '{"a":' * 1100 + "1" + "}" * 1100
        with self.assertRaisesRegex(RequestLimitError, "嵌套过深"):
            self.read(deeply_nested, max_bytes=10000)

    def test_rejects_incomplete_body_and_timeout(self):
        with self.assertRaisesRegex(RequestLimitError, "不完整"):
            read_json_object(io.BytesIO(b"{}"), {"Content-Length": "3"},
                             FakeConnection(), max_bytes=10, max_depth=4,
                             timeout_seconds=1)

        connection = FakeConnection()
        connection.timeout = 30
        with self.assertRaises(RequestLimitError) as caught:
            read_json_object(TimeoutReader(), {"Content-Length": "2"}, connection,
                             max_bytes=10, max_depth=4, timeout_seconds=1)
        self.assertEqual(caught.exception.status, 408)
        self.assertEqual(connection.timeout, 30)


class SlidingWindowLimiterTest(unittest.TestCase):
    def test_limits_each_key_and_recovers_after_window(self):
        limiter = SlidingWindowLimiter(period_seconds=60)
        self.assertTrue(limiter.allow("a", 2, now=0))
        self.assertTrue(limiter.allow("a", 2, now=1))
        self.assertFalse(limiter.allow("a", 2, now=2))
        self.assertTrue(limiter.allow("b", 2, now=2))
        self.assertTrue(limiter.allow("a", 2, now=60))

    def test_cleanup_removes_stale_keys(self):
        limiter = SlidingWindowLimiter(period_seconds=60)
        limiter.allow("a", 1, now=0)
        limiter.allow("b", 1, now=30)
        self.assertEqual(limiter.cleanup(now=61), 1)
        self.assertFalse(limiter.allow("b", 1, now=61))


class AgentSessionPoolTest(unittest.TestCase):
    def test_ttl_cleanup_skips_busy_session(self):
        pool = AgentSessionPool(2, 10)
        value, created = pool.checkout("a", lambda: object(), now=0)
        self.assertTrue(created)
        self.assertIsNotNone(value)
        self.assertEqual(pool.cleanup(now=20), 0)
        pool.release("a", now=20)
        self.assertEqual(pool.cleanup(now=31), 1)

    def test_evicts_least_recently_used_idle_session(self):
        pool = AgentSessionPool(2, 100)
        pool.checkout("a", lambda: "a", now=0)
        pool.release("a", now=1)
        pool.checkout("b", lambda: "b", now=2)
        pool.release("b", now=3)
        pool.checkout("a", lambda: "unused", now=4)
        pool.release("a", now=5)

        value, created = pool.checkout("c", lambda: "c", now=6)
        self.assertEqual(value, "c")
        self.assertTrue(created)
        pool.release("c", now=7)
        self.assertTrue(pool.exists("a", now=7))
        self.assertFalse(pool.exists("b", now=7))

    def test_busy_session_rejects_parallel_checkout_and_close(self):
        pool = AgentSessionPool(1, 100)
        pool.checkout("a", lambda: "a", now=0)
        with self.assertRaises(SessionBusyError):
            pool.checkout("a", lambda: "unused", now=1)
        with self.assertRaises(SessionBusyError):
            pool.close("a")
        pool.release("a", now=2)
        self.assertTrue(pool.close("a"))
        self.assertFalse(pool.close("missing"))

    def test_capacity_does_not_evict_busy_session(self):
        pool = AgentSessionPool(1, 100)
        pool.checkout("a", lambda: "a", now=0)
        with self.assertRaises(SessionCapacityError):
            pool.checkout("b", lambda: "b", now=1)
        pool.release("a", now=2)

    def test_factory_failure_keeps_lru_session(self):
        pool = AgentSessionPool(1, 100)
        pool.checkout("a", lambda: "a", now=0)
        pool.release("a", now=1)

        def fail():
            raise RuntimeError("init failed")

        with self.assertRaisesRegex(RuntimeError, "init failed"):
            pool.checkout("b", fail, now=2)
        self.assertTrue(pool.exists("a", now=2))
        self.assertFalse(pool.exists("b", now=2))


class ServerResourceLimitTest(unittest.TestCase):
    def setUp(self):
        self.pool = AgentSessionPool(2, 100)
        self.limits = dict(server._LIMIT_DEFAULTS)
        self.httpd = server.ResourceLimitedHTTPServer(
            ("127.0.0.1", 0), server.Handler, max_concurrent_requests=1)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.patches = [
            patch.object(server, "_agent_sessions", self.pool),
            patch.object(server, "_chat_limiter", SlidingWindowLimiter()),
            patch.object(server, "_session_create_limiter", SlidingWindowLimiter()),
            patch.object(server, "LIMITS", self.limits),
        ]
        for item in self.patches:
            item.start()
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()

    def post(self, path, value):
        connection = http.client.HTTPConnection(*self.httpd.server_address, timeout=2)
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        connection.request("POST", path, body=body,
                           headers={"Content-Type": "application/json",
                                    "Content-Length": str(len(body))})
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, payload

    def test_session_close_removes_idle_agent(self):
        self.pool.checkout("session-a", lambda: object(), now=0)
        self.pool.release("session-a", now=1)
        status, payload = self.post("/api/session/close", {"session_id": "session-a"})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "closed": True})
        self.assertFalse(self.pool.exists("session-a"))

    def test_session_close_rejects_busy_agent(self):
        self.pool.checkout("session-a", lambda: object(), now=0)
        status, payload = self.post("/api/session/close", {"session_id": "session-a"})
        self.assertEqual(status, 409)
        self.assertIn("正在处理", payload["error"])
        self.pool.release("session-a", now=1)

    def test_session_close_rejects_active_claude_session(self):
        self.assertTrue(server._claim_claude_session("session-c"))
        try:
            status, payload = self.post(
                "/api/session/close", {"session_id": "session-c"})
        finally:
            server._release_claude_session("session-c")
        self.assertEqual(status, 409)
        self.assertIn("正在处理", payload["error"])

    def test_chat_rejects_long_message_before_agent_creation(self):
        self.limits["message_max_chars"] = 3
        status, payload = self.post("/api/chat", {"message": "abcd"})
        self.assertEqual(status, 413)
        self.assertEqual(payload["error"], "message 过长")
        self.assertEqual(self.pool.count(), 0)

    def test_chat_rate_limit_returns_429(self):
        self.limits["chat_rate_per_minute"] = 1
        first_status, _ = self.post("/api/chat", {})
        second_status, payload = self.post("/api/chat", {})
        self.assertEqual(first_status, 400)
        self.assertEqual(second_status, 429)
        self.assertIn("过于频繁", payload["error"])

    def test_engine_rejects_excessive_json_depth(self):
        self.limits["json_max_depth"] = 2
        status, payload = self.post(
            "/api/engine", {"槽位": 0, "行为": [{"嵌套": {"值": 1}}]})
        self.assertEqual(status, 400)
        self.assertIn("嵌套过深", payload["error"])

    def test_server_rejects_request_when_concurrency_slot_is_full(self):
        self.assertTrue(self.httpd._request_slots.acquire(blocking=False))
        try:
            connection = http.client.HTTPConnection(*self.httpd.server_address, timeout=2)
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
        finally:
            self.httpd._request_slots.release()
        self.assertEqual(response.status, 503)
        self.assertIn("服务繁忙", payload["error"])


if __name__ == "__main__":
    unittest.main()
