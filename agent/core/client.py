"""OpenAI 兼容的 Chat Completions HTTP 客户端 (仅依赖标准库)。"""

import json
import os
import urllib.request
import urllib.error


class ContextOverflowError(RuntimeError):
    """服务端判断请求上下文超出模型窗口 (400/413 且响应体含超限线索)。"""


_OVERFLOW_KEYS = (
    "context length", "context_length", "too many tokens", "maximum context",
    "length exceeded", "prompt is too long", "schema_overflow", "exceed the",
    "tokens must", "最大上下文", "上下文超", "长度超", "超出最大", "超长",
)


class ChatClient:
    def __init__(self, base_url=None, model=None, api_token=None, timeout=120):
        self.base_url = (
            base_url
            or os.environ.get("AGENT_API_BASE")
        )
        if not self.base_url:
            raise RuntimeError(
                "未配置 LLM 服务地址: 请在 config.json 的 llm.base_url 中设置, "
                "或导出环境变量 AGENT_API_BASE。"
            )
        self.base_url = self.base_url.rstrip("/")
        self.model = model or os.environ.get("AGENT_MODEL")
        if not self.model:
            raise RuntimeError(
                "未配置 LLM 模型名: 请在 config.json 的 llm.model 中设置, "
                "或导出环境变量 AGENT_MODEL。"
            )
        self.api_token = (
            api_token
            if api_token is not None
            else os.environ.get("AGENT_API_TOKEN")
        )
        self.timeout = timeout

    def chat(self, messages, tools=None, temperature=None, max_tokens=None,
             reasoning_effort=None, **extra):
        """发送一次对话请求, 返回解析后的 assistant message dict。"""
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if tools:
            payload["tools"] = tools
        if max_tokens:
            payload["max_tokens"] = max_tokens
        payload.update(extra)

        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            lower = body.lower()
            if e.code == 413 or any(k in lower for k in _OVERFLOW_KEYS):
                raise ContextOverflowError(f"上下文超限 HTTP {e.code}: {body}") from e
            raise RuntimeError(f"API 请求失败 HTTP {e.code}: {body}") from e

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"API 返回了空 choices: {body}")
        return choices[0]["message"]
