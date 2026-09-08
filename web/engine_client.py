"""Web 到共享 Engine Service 的标准库客户端与子进程生命周期。"""

import json
import os
import queue
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

READY_PREFIX = "[engine-service-ready] "


class EngineClientError(RuntimeError):
    def __init__(self, message, status=500, code="engine_client_error"):
        super().__init__(message)
        self.status = status
        self.code = code


class EngineClient:
    def __init__(self, service_url, timeout_ms=120000, process=None):
        self.service_url = service_url.rstrip("/")
        self.timeout = max(float(timeout_ms) / 1000, 0.1)
        self.process = process

    @classmethod
    def connect(cls, skill_dir, service_url="", timeout_ms=120000,
                port=0, startup_timeout=10):
        service_url = (service_url or "").strip().rstrip("/")
        if service_url:
            client = cls(service_url, timeout_ms=timeout_ms)
            client._verify_health()
            return client

        script = os.path.join(skill_dir, "scripts", "engine_service.py")
        if not os.path.isfile(script):
            raise EngineClientError(f"engine service 不存在: {script}")
        instance_id = str(uuid.uuid4())
        env = dict(os.environ)
        env.update({
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "WUXIA_RPG_ENGINE_INSTANCE_ID": instance_id,
            "WUXIA_RPG_SKILL_DIR": skill_dir,
        })
        process = subprocess.Popen(
            [sys.executable, script], env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        ready_queue = queue.Queue(maxsize=1)

        def pump_stdout():
            for raw in process.stdout or ():
                line = raw.rstrip()
                if line.startswith(READY_PREFIX) and ready_queue.empty():
                    try:
                        ready_queue.put_nowait(json.loads(line[len(READY_PREFIX):]))
                    except (ValueError, json.JSONDecodeError) as exc:
                        ready_queue.put_nowait(exc)
                elif line:
                    print(f"[engine-service] {line}")

        def pump_stderr():
            for raw in process.stderr or ():
                line = raw.rstrip()
                if line:
                    print(f"[engine-service] {line}", file=sys.stderr)

        threading.Thread(target=pump_stdout, daemon=True).start()
        threading.Thread(target=pump_stderr, daemon=True).start()
        try:
            ready = ready_queue.get(timeout=startup_timeout)
            if isinstance(ready, Exception):
                raise ready
            if process.poll() is not None:
                raise EngineClientError(f"engine service 提前退出: {process.returncode}")
            if ready.get("engine") is not True:
                raise EngineClientError("engine service 导入引擎失败")
            if ready.get("instance_id") != instance_id:
                raise EngineClientError("engine service 实例标识不匹配")
            actual_port = ready.get("port")
            if not isinstance(actual_port, int) or actual_port <= 0:
                raise EngineClientError("engine service 返回端口无效")
            client = cls(f"http://127.0.0.1:{actual_port}", timeout_ms, process)
            client._verify_health(expected_instance=instance_id)
            return client
        except Exception as exc:
            cls("", timeout_ms=timeout_ms, process=process).close()
            if isinstance(exc, EngineClientError):
                raise
            if isinstance(exc, queue.Empty):
                raise EngineClientError("engine service 启动超时") from exc
            raise EngineClientError(f"engine service 启动失败: {exc}") from exc

    def close(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()

    def get_tools(self):
        return self._request("GET", "/api/tools")

    def call_operation(self, operation, payload):
        path = "/api/v1/operations/" + urllib.parse.quote(operation, safe="-")
        return self._request("POST", path, payload)

    def _verify_health(self, expected_instance=None):
        health = self._request("GET", "/api/health")
        if health.get("ok") is not True or health.get("engine") is not True:
            raise EngineClientError("engine service 未就绪", status=503)
        if health.get("service") != "wuxia-rpg-engine":
            raise EngineClientError("engine service 标识不匹配")
        if expected_instance is not None and health.get("instance_id") != expected_instance:
            raise EngineClientError("engine service health 实例标识不匹配")

    def _request(self, method, path, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.service_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {}
            raise EngineClientError(
                body.get("error") or f"engine service HTTP {exc.code}",
                status=exc.code, code=body.get("code") or "engine_http_error") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise EngineClientError(f"engine service 调用失败: {exc}") from exc
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EngineClientError(f"engine service 输出非 JSON: {raw[:200]}") from exc
        if not isinstance(body, dict):
            raise EngineClientError("engine service 输出须为 JSON 对象")
        return body
