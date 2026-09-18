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
             reasoning_effort=None, on_reasoning=None, on_content=None, **extra):
        """发送一次对话请求, 返回解析后的 assistant message dict。

        传入 on_reasoning / on_content 时走流式: 思考与正文片段逐段回调,
        结束后返回拼装完整的 message (tool_calls 按 index 增量合成);
        网关不支持流式 (HTTP 400) 时回退非流式, 整段一次性回调。
        """
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

        stream = on_reasoning is not None or on_content is not None
        if not stream:
            return self._chat_once(payload)
        payload["stream"] = True
        try:
            return self._chat_stream(payload, on_reasoning, on_content)
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                self._raise_http(exc)
            # 网关不支持流式: 回退非流式, 整段一次性回调
            payload.pop("stream", None)
            message = self._chat_once(payload)
            if on_reasoning and message.get("reasoning_content"):
                on_reasoning(message["reasoning_content"])
            if on_content and message.get("content"):
                on_content(message["content"])
            return message

    # ---------- 内部: 请求构造与非流式 ----------

    def _request(self, payload):
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    @staticmethod
    def _raise_http(exc):
        body = exc.read().decode("utf-8", "ignore")
        lower = body.lower()
        if exc.code == 413 or any(k in lower for k in _OVERFLOW_KEYS):
            raise ContextOverflowError(f"上下文超限 HTTP {exc.code}: {body}") from exc
        raise RuntimeError(f"API 请求失败 HTTP {exc.code}: {body}") from exc

    def _chat_once(self, payload):
        try:
            with urllib.request.urlopen(self._request(payload), timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._raise_http(exc)

        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError(f"API 返回了空 choices: {body}")
        return choices[0]["message"]

    # ---------- 内部: 流式 ----------

    def _chat_stream(self, payload, on_reasoning, on_content):
        """逐行读取 SSE chunk, 增量回调并合成完整 message。"""
        content_parts = []
        reasoning_parts = []
        tool_calls = {}
        with urllib.request.urlopen(self._request(payload), timeout=self.timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("reasoning_content") or delta.get("reasoning")
                if piece:
                    reasoning_parts.append(piece)
                    if on_reasoning:
                        on_reasoning(piece)
                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
                    if on_content:
                        on_content(piece)
                for part in delta.get("tool_calls") or []:
                    slot = tool_calls.setdefault(part.get("index", 0), {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    if part.get("id"):
                        slot["id"] = part["id"]
                    fn = part.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]

        message = {"role": "assistant", "content": "".join(content_parts)}
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        if tool_calls:
            message["tool_calls"] = [tool_calls[key] for key in sorted(tool_calls)]
        if not message["content"] and not message.get("tool_calls"):
            raise RuntimeError("API 流式返回了空 message")
        return message
