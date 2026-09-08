#!/usr/bin/env python3
"""武侠RPG 共享 Engine Service；仅负责 HTTP、生命周期与 Gateway 转发。"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.environ.get("WUXIA_RPG_SKILL_DIR") or os.path.dirname(HERE)
INSTANCE_ID = os.environ.get("WUXIA_RPG_ENGINE_INSTANCE_ID", "")
REQUEST_LIMIT = int(os.environ.get("WUXIA_RPG_ENGINE_REQUEST_LIMIT", "2000000"))

if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from engine_gateway import EngineGateway, GatewayError, load_tools_manifest
    _manifest = load_tools_manifest(os.path.join(SKILL_DIR, "tools.json"))
    _gateway = EngineGateway(manifest=_manifest)
    _startup_error = ""
except Exception as exc:  # noqa: BLE001
    _manifest = None
    _gateway = None
    _startup_error = str(exc)
    print(f"[engine-service] 初始化失败: {exc}", file=sys.stderr, flush=True)


_COMPAT_PATHS = {
    "/api/check": "check",
    "/api/random-event": "random-event",
    "/api/query": "query",
    "/api/setting": "setting",
    "/api/recommend": "recommend",
    "/api/map-query": "map-query",
}


class EngineHandler(BaseHTTPRequestHandler):
    server_version = "WuxiaEngine/2.0"

    def log_message(self, fmt, *args):
        print(f"[{self.command}] {self.path} {args[0] if args else ''}")

    def do_GET(self):
        if self.path == "/api/health":
            self._json({
                "ok": _gateway is not None,
                "service": "wuxia-rpg-engine",
                "instance_id": INSTANCE_ID,
                "engine": _gateway is not None,
                "protocol_version": (_manifest or {}).get("protocol_version", ""),
                **({"error": _startup_error} if _startup_error else {}),
            }, 200 if _gateway is not None else 503)
            return
        if self.path == "/api/tools":
            if _manifest is None:
                self._json({"error": _startup_error or "tools manifest 不可用"}, 503)
            else:
                self._json(_manifest)
            return
        self._json({"error": "not found", "code": "not_found"}, 404)

    def do_POST(self):
        payload = self._read_payload()
        if payload is None:
            return

        if self.path.startswith("/api/v1/operations/"):
            operation = unquote(self.path[len("/api/v1/operations/"):])
            if not operation or "/" in operation:
                self._json({"error": "operation 路径无效", "code": "invalid_request"}, 400)
                return
            self._invoke(operation, payload)
            return

        if self.path == "/api/engine":
            operation = payload.get("method", "go")
            if operation not in ("go", "judge"):
                self._json({"error": "method 仅允许 go/judge", "code": "invalid_request"}, 400)
                return
            self._invoke(operation, {k: v for k, v in payload.items() if k != "method"})
            return

        operation = _COMPAT_PATHS.get(self.path)
        if operation:
            self._invoke(operation, payload)
            return

        self._json({"error": "not found", "code": "not_found"}, 404)

    def _read_payload(self):
        try:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self._json({"error": "缺少 Content-Length", "code": "length_required"}, 411)
                return None
            length = int(raw_length)
            if length < 0:
                raise ValueError
            if length > REQUEST_LIMIT:
                self._json({"error": "请求体过大", "code": "request_too_large"}, 413)
                return None
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
        except UnicodeDecodeError:
            self._json({"error": "请求体须为 UTF-8", "code": "invalid_encoding"}, 400)
            return None
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "invalid json", "code": "invalid_json"}, 400)
            return None
        if not isinstance(payload, dict):
            self._json({"error": "payload 须为 JSON 对象", "code": "invalid_request"}, 400)
            return None
        return payload

    def _invoke(self, operation, payload):
        if _gateway is None:
            self._json({"error": _startup_error or "engine 不可用", "code": "engine_unavailable"}, 503)
            return
        try:
            result = _gateway.invoke(operation, payload)
        except GatewayError as exc:
            self._json({"error": str(exc), "code": exc.code}, exc.status)
            return
        self._json(result)

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


class EngineServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    port = int(os.environ.get("PORT", "0"))
    host = os.environ.get("HOST", "127.0.0.1")
    server = EngineServer((host, port), EngineHandler)
    actual_port = int(server.server_address[1])
    ready = {
        "host": host,
        "port": actual_port,
        "service": "wuxia-rpg-engine",
        "engine": _gateway is not None,
        "protocol_version": (_manifest or {}).get("protocol_version", ""),
        "instance_id": INSTANCE_ID,
    }
    print(f"[engine-service-ready] {json.dumps(ready, ensure_ascii=False)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[engine-service] 停止", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
