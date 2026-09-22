#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""压缩摘要输入对 thinking / 工具调用内容的过滤开关。"""

import os
import sys
import unittest

AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT not in sys.path:
    sys.path.insert(0, AGENT)

from core.agent import Agent, _format_for_summary


def call_msg():
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "read", "arguments": "{}"}},
    ], "reasoning_content": "调用前思考"}


def tool_msg():
    return {"role": "tool", "tool_call_id": "c1", "name": "read", "content": "文件内容"}


class FormatForSummaryTest(unittest.TestCase):
    def test_default_excludes_thinking_and_tools(self):
        messages = [
            call_msg(),
            tool_msg(),
            {"role": "assistant", "content": "答完了", "reasoning_content": "尾思"},
            {"role": "user", "content": "下一问"},
        ]

        self.assertEqual(_format_for_summary(messages), [
            "assistant: 答完了",
            "user: 下一问",
        ])

    def test_include_tools_keeps_tool_results_and_call_names(self):
        messages = [call_msg(), tool_msg()]

        lines = _format_for_summary(messages, include_tools=True)

        self.assertEqual(lines, [
            "assistant:  [调工具: read]",
            "tool: 文件内容",
        ])

    def test_include_thinking_prepends_reasoning(self):
        messages = [call_msg(), {"role": "assistant", "content": "答完了", "reasoning_content": "尾思"}]

        lines = _format_for_summary(messages, include_thinking=True)

        self.assertEqual(lines, [
            "assistant: [思考] 调用前思考\n",
            "assistant: [思考] 尾思\n答完了",
        ])


class SummarizeSwitchWiringTest(unittest.TestCase):
    """Agent 把 session.compress_* 透传到摘要输入 (默认不进)。"""

    @staticmethod
    def _agent():
        captured = {}

        class StubClient:
            model = "stub"
            def chat(self, messages, **kwargs):
                captured["messages"] = messages
                return {"role": "assistant", "content": "摘要正文"}

        return Agent(client=StubClient()), captured

    def test_summarize_input_follows_compress_switches(self):
        agent, captured = self._agent()
        agent.session.messages = [
            call_msg(),
            tool_msg(),
            {"role": "assistant", "content": "答完了"},
            {"role": "user", "content": "下一问"},
        ]
        agent.session.max_context_tokens = 1  # 触发压缩
        agent.session.get_messages()

        user = captured["messages"][1]["content"]
        self.assertIn("assistant: 答完了", user)
        self.assertNotIn("文件内容", user)      # 工具结果默认不进压缩
        self.assertNotIn("调工具", user)        # 工具调用名默认不进压缩
        self.assertEqual(agent.session.summary, "摘要正文")

        # 开关打开后工具内容进入压缩输入
        agent2, captured2 = self._agent()
        agent2.session.compress_tools = True
        agent2.session.messages = [
            call_msg(),
            tool_msg(),
            {"role": "assistant", "content": "答完了"},
            {"role": "user", "content": "下一问"},
        ]
        agent2.session.max_context_tokens = 1
        agent2.session.get_messages()

        self.assertIn("文件内容", captured2["messages"][1]["content"])
        self.assertIn("调工具: read", captured2["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
