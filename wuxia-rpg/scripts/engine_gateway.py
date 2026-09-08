#!/usr/bin/env python3
"""Tools Schema 与 engine.py 之间的唯一分发边界。"""

import importlib
import os
import threading

from common.json_io import JsonReadError, read_json

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_PATH = os.path.join(SKILL_DIR, "tools.json")
_ENGINE_LOCK = threading.Lock()
_SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}


class GatewayError(Exception):
    """可稳定映射为 HTTP/工具错误的 Gateway 异常。"""

    def __init__(self, message, code="gateway_error", status=500):
        super().__init__(message)
        self.code = code
        self.status = status


class GatewayProtocolError(GatewayError):
    def __init__(self, message, code="invalid_request", status=400):
        super().__init__(message, code=code, status=status)


def _validate_schema(node, path):
    if not isinstance(node, dict):
        raise ValueError(f"{path} 须为对象")
    schema_type = node.get("type")
    if schema_type not in _SCHEMA_TYPES:
        raise ValueError(f"{path}.type 不支持: {schema_type}")
    if "description" in node and not isinstance(node["description"], str):
        raise ValueError(f"{path}.description 须为字符串")
    if schema_type == "object":
        props = node.get("properties", {})
        if not isinstance(props, dict):
            raise ValueError(f"{path}.properties 须为对象")
        required = node.get("required", [])
        if not isinstance(required, list) or any(not isinstance(v, str) for v in required):
            raise ValueError(f"{path}.required 须为字符串数组")
        missing = set(required) - set(props)
        if missing:
            raise ValueError(f"{path}.required 引用了未知字段: {sorted(missing)}")
        if node.get("additionalProperties", True) not in (True, False):
            raise ValueError(f"{path}.additionalProperties 须为布尔值")
        for name, child in props.items():
            _validate_schema(child, f"{path}.properties.{name}")
    elif schema_type == "array" and "items" in node:
        _validate_schema(node["items"], f"{path}.items")


def load_tools_manifest(path=TOOLS_PATH):
    """读取并校验受控的 Tools Schema manifest。"""
    manifest = read_json(path, expected_type=dict)
    version = manifest.get("protocol_version")
    tools = manifest.get("tools")
    if not isinstance(version, str) or not version:
        raise ValueError("tools manifest 缺少 protocol_version")
    if not isinstance(tools, list) or not tools:
        raise ValueError("tools manifest 缺少 tools")
    names = set()
    operations = set()
    for index, tool in enumerate(tools):
        path_prefix = f"tools[{index}]"
        if not isinstance(tool, dict):
            raise ValueError(f"{path_prefix} 须为对象")
        for key in ("name", "operation", "title", "description"):
            if not isinstance(tool.get(key), str) or not tool[key]:
                raise ValueError(f"{path_prefix}.{key} 缺失")
        if tool["name"] in names:
            raise ValueError(f"工具名重复: {tool['name']}")
        if tool["operation"] in operations:
            raise ValueError(f"operation 重复: {tool['operation']}")
        names.add(tool["name"])
        operations.add(tool["operation"])
        _validate_schema(tool.get("input_schema"), f"{path_prefix}.input_schema")
        _validate_schema(tool.get("output_schema"), f"{path_prefix}.output_schema")
        if tool["input_schema"].get("type") != "object":
            raise ValueError(f"{path_prefix}.input_schema 须为 object")
    return manifest


class EngineGateway:
    """串行调用确定性引擎的 operation 白名单。"""

    def __init__(self, engine_module=None, manifest=None, lock=None):
        self.engine = engine_module or importlib.import_module("engine")
        self.manifest = manifest or load_tools_manifest()
        self.lock = lock or _ENGINE_LOCK
        self._handlers = {
            "go": self._go,
            "judge": self._judge,
            "check": self.engine.check,
            "random-event": self.engine.random_event,
            "query": self.engine.query,
            "setting": self.engine.setting,
            "recommend": self.engine.recommend,
            "map-query": self.engine.map_query,
        }
        declared = {tool["operation"] for tool in self.manifest["tools"]}
        implemented = set(self._handlers)
        if declared != implemented:
            missing = sorted(declared - implemented)
            extra = sorted(implemented - declared)
            raise ValueError(f"Tools Schema 与 Gateway 不一致: missing={missing}, extra={extra}")

    @property
    def operations(self):
        return tuple(self._handlers)

    def invoke(self, operation, payload):
        if not isinstance(operation, str) or not operation:
            raise GatewayProtocolError("缺少 operation")
        handler = self._handlers.get(operation)
        if handler is None:
            raise GatewayProtocolError(
                f"未知 operation: {operation}", code="unknown_operation", status=404)
        if not isinstance(payload, dict):
            raise GatewayProtocolError("payload 须为 JSON 对象")
        self._require_slot(payload, operation)
        try:
            with self.lock:
                return handler(payload)
        except GatewayError:
            raise
        except JsonReadError as exc:
            raise GatewayError(str(exc), code=exc.code, status=500) from exc
        except Exception as exc:  # noqa: BLE001
            raise GatewayError(f"{operation} 调用异常: {exc}", code="engine_error") from exc

    @staticmethod
    def _require_slot(payload, operation):
        slot = payload.get("槽位")
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
            raise GatewayProtocolError(f"{operation} 缺少有效 槽位")
        return slot

    def _go(self, payload):
        actions = payload.get("行为")
        if not isinstance(actions, list):
            raise GatewayProtocolError("go 缺少 行为（数组）")
        return self.engine.go(payload["槽位"], actions)

    def _judge(self, payload):
        actions = payload.get("行为")
        if not isinstance(actions, list):
            raise GatewayProtocolError("judge 缺少 行为（数组）")
        return self.engine.judge(payload["槽位"], payload)
