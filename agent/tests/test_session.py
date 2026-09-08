#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Session 工具消息分组与上下文裁剪。"""

import os
import sys
import unittest

AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AGENT not in sys.path:
    sys.path.insert(0, AGENT)

from core.session import Session, _tool_call_group_size


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

    def test_fallback_trim_never_leaves_orphaned_tool_results(self):
        session = Session(max_context_tokens=11)
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


if __name__ == "__main__":
    unittest.main()
