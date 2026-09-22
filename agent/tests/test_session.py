#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session 工具消息分组与上下文裁剪。"""

import json
import os
import sys
import unittest

AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT not in sys.path:
    sys.path.insert(0, AGENT)

from core.session import (
    SKILL_TOOL,
    Session,
    _normalize_tool_messages,
    _tool_call_group_size,
)


def assistant_calls(*call_ids):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "test", "arguments": ""},
            }
            for call_id in call_ids
        ],
    }


def tool_result(call_id):
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": "test",
        "content": "",
    }


def message(role):
    return {"role": role, "content": ""}


class SessionToolGroupingTest(unittest.TestCase):
    def test_group_contains_only_adjacent_matching_tool_results(self):
        messages = [
            assistant_calls("call_a"),
            tool_result("call_a"),
            message("assistant"),
            message("user"),
            assistant_calls("call_b"),
            tool_result("call_b"),
        ]

        self.assertEqual(_tool_call_group_size(messages, 0), 2)
        self.assertEqual(_tool_call_group_size(messages, 4), 2)
        self.assertEqual(
            _tool_call_group_size([
                assistant_calls("call_a"),
                tool_result("call_other"),
            ], 0),
            1,
        )

    def test_normalize_keeps_complete_results_in_any_order(self):
        messages = [
            assistant_calls("call_a", "call_b"),
            tool_result("call_b"),
            tool_result("call_a"),
            message("user"),
        ]

        kept, dropped = _normalize_tool_messages(messages)

        self.assertEqual(kept, messages)
        self.assertEqual(dropped, [])

    def test_normalize_drops_incomplete_mismatched_and_orphaned_results(self):
        user = message("user")
        messages = [
            tool_result("orphan"),
            assistant_calls("missing"),
            user,
            assistant_calls("call_a"),
            tool_result("call_other"),
            message("assistant"),
        ]

        kept, dropped = _normalize_tool_messages(messages)

        self.assertEqual(kept, [user, messages[-1]])
        self.assertEqual(dropped, messages[:2] + messages[3:5])

    def test_normalize_drops_duplicate_call_ids(self):
        messages = [
            assistant_calls("duplicate", "duplicate"),
            tool_result("duplicate"),
            tool_result("duplicate"),
            message("user"),
        ]

        kept, dropped = _normalize_tool_messages(messages)

        self.assertEqual(kept, [messages[-1]])
        self.assertEqual(dropped, messages[:-1])

    def test_compression_does_not_swallow_later_turns(self):
        session = Session(max_context_tokens=12, compress_target_ratio=0.9)
        session.messages = [
            assistant_calls("call_a"),
            tool_result("call_a"),
            message("assistant"),
            message("user"),
            assistant_calls("call_b1", "call_b2"),
            tool_result("call_b1"),
            tool_result("call_b2"),
            message("assistant"),
        ]
        dropped = []
        session.on_drop = dropped.extend

        output = session.get_messages()

        self.assertEqual(len(dropped), 2)
        self.assertEqual(dropped[0]["tool_calls"][0]["id"], "call_a")
        self.assertEqual(dropped[1]["tool_call_id"], "call_a")
        self.assertEqual(output[0]["role"], "assistant")
        self.assertNotIn("tool_calls", output[0])

    def test_export_removes_invalid_tool_fragments_before_compression(self):
        session = Session(max_context_tokens=10, compress_target_ratio=0.9)
        session.messages = [
            assistant_calls("call_a"),
            tool_result("call_other"),
            {"role": "user", "content": "end"},
        ]
        dropped = []
        session.on_drop = dropped.extend

        output = session.get_messages()

        self.assertEqual(output, [{"role": "user", "content": "end"}])
        self.assertEqual(dropped, [
            assistant_calls("call_a"),
            tool_result("call_other"),
        ])

    def test_fallback_trim_never_leaves_orphaned_tool_results(self):
        # include_tools=True: 关闭历史剥离, 保持该用例聚焦兜底裁剪本身
        session = Session(max_context_tokens=11, include_tools=True)
        session.messages = [
            assistant_calls("call_a"),
            tool_result("call_a"),
            message("assistant"),
            message("user"),
            assistant_calls("call_b1", "call_b2", "call_b3", "call_b4"),
            tool_result("call_b1"),
            tool_result("call_b2"),
            tool_result("call_b3"),
            tool_result("call_b4"),
            message("assistant"),
        ]
        session._maybe_compress = lambda: None

        output = session.get_messages()

        self.assertEqual(output[0]["role"], "assistant")
        self.assertEqual(
            [call["id"] for call in output[0]["tool_calls"]],
            ["call_b1", "call_b2", "call_b3", "call_b4"],
        )
        self.assertEqual(
            [item["tool_call_id"] for item in output[1:5]],
            ["call_b1", "call_b2", "call_b3", "call_b4"],
        )


class SessionHistoryStrippingTest(unittest.TestCase):
    """历史轮 thinking / 工具调用内容的拼接开关 (默认都不拼)。"""

    def _session(self, **kwargs):
        session = Session(**kwargs)
        session.messages = [
            # 历史轮: 纯工具调用 + 结果
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "old_1", "type": "function",
                 "function": {"name": "test", "arguments": ""}},
            ], "reasoning_content": "旧思考"},
            tool_result("old_1"),
            # 历史轮: 带正文的最终回复
            {"role": "assistant", "content": "答完了", "reasoning_content": "尾思"},
            # 当前轮 (最后一条 user 起)
            message("user"),
            assistant_calls("cur_1"),
            tool_result("cur_1"),
            {"role": "assistant", "content": "最终回复", "reasoning_content": "新思考"},
        ]
        return session

    def test_default_strips_history_thinking_and_tools(self):
        output = self._session().get_messages()

        self.assertEqual(output, [
            {"role": "assistant", "content": "答完了"},
            message("user"),
            assistant_calls("cur_1"),
            tool_result("cur_1"),
            {"role": "assistant", "content": "最终回复", "reasoning_content": "新思考"},
        ])

    def test_include_tools_keeps_history_tool_groups(self):
        output = self._session(include_tools=True).get_messages()

        self.assertEqual(output[0]["tool_calls"][0]["id"], "old_1")
        self.assertEqual(output[1]["tool_call_id"], "old_1")
        self.assertNotIn("reasoning_content", output[2])  # thinking 默认仍不拼

    def test_include_thinking_keeps_history_reasoning(self):
        output = self._session(include_thinking=True).get_messages()

        self.assertEqual(output[0]["content"], "答完了")
        self.assertEqual(output[0]["reasoning_content"], "尾思")

    def test_storage_untouched_by_stripping(self):
        session = self._session()
        session.get_messages()

        self.assertIn("tool_calls", session.messages[0])
        self.assertIn("reasoning_content", session.messages[0])
        self.assertEqual(len(session.messages), 7)


class SessionSkillExemptionTest(unittest.TestCase):
    """use_skill 豁免: 历史剥离保留, 压缩提取持久化并拼回, 不进摘要输入。"""

    @staticmethod
    def skill_call(call_id, skill="wuxia"):
        return {"id": call_id, "type": "function",
                "function": {"name": SKILL_TOOL,
                             "arguments": json.dumps({"name": skill})}}

    @staticmethod
    def skill_result(call_id):
        return {"role": "tool", "tool_call_id": call_id,
                "name": SKILL_TOOL, "content": "技能指令"}

    def test_history_strip_keeps_use_skill(self):
        session = Session()
        session.messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "r1", "type": "function",
                 "function": {"name": "read", "arguments": "{}"}},
                self.skill_call("s1"),
            ]},
            {"role": "tool", "tool_call_id": "r1", "name": "read", "content": "文件"},
            self.skill_result("s1"),
            message("user"),
        ]

        output = session.get_messages()

        self.assertEqual(output[0]["tool_calls"], [self.skill_call("s1")])
        self.assertEqual(output[1]["tool_call_id"], "s1")
        self.assertEqual(output[2], message("user"))

    def test_compression_extracts_skill_and_splices_back(self):
        seen = []
        session = Session(
            summarizer=lambda dropped, prev: seen.append(dropped) or "摘要")
        session.messages = [
            {"role": "assistant", "content": "", "tool_calls": [self.skill_call("s1")],
             "reasoning_content": "加载前思考"},
            self.skill_result("s1"),
            message("user"),
        ]

        session.force_compress()
        output = session.get_messages()

        self.assertEqual(seen, [[]])  # 技能内容不进摘要输入
        self.assertEqual(session.summary, "摘要")
        self.assertEqual(len(session.skill_calls), 1)
        # 拼回头部: assistant(use_skill 调用) + tool(指令)
        self.assertEqual(output[1]["tool_calls"], [self.skill_call("s1")])
        self.assertEqual(output[2]["tool_call_id"], "s1")
        self.assertEqual(output[3], message("user"))

    def test_splice_skips_skills_already_in_messages(self):
        session = Session()
        session.messages = [
            message("user"),
            {"role": "assistant", "content": "", "tool_calls": [self.skill_call("s2")]},
            self.skill_result("s2"),
        ]
        session._add_skill_calls([(self.skill_call("s1"), self.skill_result("s1"))])

        output = session.get_messages()

        contents = [m["content"] for m in output if m.get("role") == "tool"]
        self.assertEqual(contents, ["技能指令"])  # s1 已被 s2 覆盖, 不重复拼接

    def test_drop_head_extracts_skill(self):
        session = Session()
        session.messages = [
            {"role": "assistant", "content": "", "tool_calls": [self.skill_call("s1")]},
            self.skill_result("s1"),
            message("user"),
        ]

        rest = session.drop_head(2)

        self.assertEqual(rest, [])
        self.assertEqual(len(session.skill_calls), 1)
        self.assertEqual(session.messages, [message("user")])


class ReadReferenceExemptionTest(unittest.TestCase):
    """wuxia_read_reference 仅历史拼接豁免, 压缩照常 (不提取、不豁免)。"""

    REF_CALL = {"id": "rr1", "type": "function",
                "function": {"name": "wuxia_read_reference", "arguments": "{}"}}
    REF_RESULT = {"role": "tool", "tool_call_id": "rr1",
                  "name": "wuxia_read_reference", "content": "规则文档"}

    def test_history_strip_keeps_read_reference(self):
        session = Session()
        session.messages = [
            {"role": "assistant", "content": "", "tool_calls": [self.REF_CALL]},
            self.REF_RESULT,
            message("user"),
        ]

        output = session.get_messages()

        self.assertEqual(output[0]["tool_calls"], [self.REF_CALL])
        self.assertEqual(output[1], self.REF_RESULT)
        self.assertEqual(output[2], message("user"))

    def test_compression_does_not_exempt_read_reference(self):
        seen = []
        session = Session(summarizer=lambda dropped, prev: seen.append(dropped) or "摘要")
        session.messages = [
            {"role": "assistant", "content": "", "tool_calls": [self.REF_CALL]},
            self.REF_RESULT,
            message("user"),
        ]

        session.force_compress()

        self.assertEqual(session.skill_calls, [])  # 不提取持久化
        self.assertEqual(len(seen[0]), 2)          # 照常进入压缩输入


if __name__ == "__main__":
    unittest.main()
