"""会话上下文管理: 维护消息历史, 超限先压缩为摘要, 兜底才裁剪。"""


def _estimate_tokens(text):
    """粗略估算 token 数: 英文约 4 字符/token, 中文约 1.5 字符/token, 取保守值字符数/2。"""
    return max(1, len(text) // 2)


def _tool_call_group_size(messages, start):
    """返回 assistant(tool_calls) 与紧随其后的匹配 tool 结果数量。"""
    message = messages[start]
    if message.get("role") != "assistant" or not message.get("tool_calls"):
        return 1
    pending = {
        call.get("id") for call in message["tool_calls"]
        if call.get("id")
    }
    size = 1
    for following in messages[start + 1:]:
        if following.get("role") != "tool":
            break
        call_id = following.get("tool_call_id")
        if call_id not in pending:
            break
        pending.remove(call_id)
        size += 1
        if not pending:
            break
    return size


class Session:
    def __init__(self, system_prompt="", max_context_tokens=1_000_000,
                 summarizer=None, compress_target_ratio=0.5):
        self.system_prompt = system_prompt
        self.max_context_tokens = max_context_tokens
        # summarizer(messages, prev_summary) -> str, 由 Agent 注入 (调模型压缩);
        # 为 None 时退化为直接裁剪
        self.summarizer = summarizer
        # 历史消息被压缩/裁剪丢弃时的回调 (如清空工具的 read 去重缓存),
        # 由 Agent 注入, 签名 on_drop(dropped_messages)
        self.on_drop = None
        # 压缩时把上下文压到预算的多少比例, 预留空间避免逐轮重复压缩
        self.compress_target_ratio = compress_target_ratio
        # messages 只含对话消息, system 在导出时拼接
        self.messages = []
        # 早期历史的压缩摘要, 拼接在 system 之后
        self.summary = ""

    # ---------- 消息操作 ----------

    def add_user(self, content):
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, message):
        """message 是 API 返回的 assistant dict (可能带 tool_calls)。"""
        self.messages.append(message)

    def add_tool(self, tool_call_id, name, content):
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        })

    def clear(self):
        self.messages = []
        self.summary = ""

    # ---------- token 估算 ----------

    def _message_tokens(self, msg):
        tokens = _estimate_tokens(msg.get("content") or "")
        for tc in msg.get("tool_calls") or []:
            tokens += _estimate_tokens(tc["function"].get("arguments") or "")
        return tokens

    def _total_tokens(self):
        return (_estimate_tokens(self.system_prompt)
                + _estimate_tokens(self.summary)
                + sum(self._message_tokens(m) for m in self.messages))

    # ---------- 压缩与裁剪 ----------

    def _drop_groups(self, target_tokens):
        """从头部按 tool_calls 组为单位选出待压缩/待丢弃前缀, 返回 (组列表, 剩余消息)。"""
        groups = []
        remaining = self._total_tokens()
        i = 0
        while i < len(self.messages) and remaining > target_tokens:
            gsize = _tool_call_group_size(self.messages, i)
            if i + gsize >= len(self.messages):
                break  # 至少保留最后一组
            group = self.messages[i:i + gsize]
            remaining -= sum(self._message_tokens(x) for x in group)
            groups.append(group)
            i += gsize
        return groups, self.messages[i:]

    def _compress_to(self, target_tokens):
        """核心: 按组选前缀, summarizer 压成摘要, 移除原消息。返回是否真的进行了压缩。"""
        groups, kept = self._drop_groups(target_tokens)
        if not groups:
            return False
        dropped = [m for g in groups for m in g]
        if self.summarizer:
            try:
                new_summary = self.summarizer(dropped, self.summary)
            except Exception:  # noqa: BLE001 - 压缩失败不致命, 退化为裁剪
                new_summary = None
            if new_summary:
                self.summary = new_summary
        self.messages = kept
        if self.on_drop:
            self.on_drop(dropped)
        return True

    def _maybe_compress(self):
        if self._total_tokens() <= self.max_context_tokens:
            return
        target = int(self.max_context_tokens * self.compress_target_ratio)
        self._compress_to(target)

    def force_compress(self, ratio=0.5):
        """API 报上下文超限时主动压缩: 无视预算, 把历史压到当前的 ratio 比例。
        返回是否确实有内容被压缩 (无可压内容时重试也是白压, 应放弃)。"""
        target = max(1, int(self._total_tokens() * ratio))
        return self._compress_to(target)

    def _system_prompt_out(self):
        if self.summary:
            return (self.system_prompt + "\n\n"
                    "## 早期对话摘要 (已压缩的历史, 其中事实仍然有效)\n"
                    + self.summary)
        return self.system_prompt

    def get_messages(self):
        """导出完整 messages (含 system 与历史摘要)。超限先压缩, 兜底再裁剪。"""
        self._maybe_compress()
        # 兜底裁剪: 无 summarizer 或压缩结果仍超限时, 保证输出有界
        budget = self.max_context_tokens - _estimate_tokens(self._system_prompt_out())
        msg_tokens = [self._message_tokens(m) for m in self.messages]
        msgs = list(self.messages)
        trimmed = 0
        while msgs and sum(msg_tokens) > budget:
            drop = _tool_call_group_size(msgs, 0)
            msg_tokens = msg_tokens[drop:]
            msgs = msgs[drop:]
            trimmed += drop
        if trimmed and self.on_drop:
            self.on_drop(self.messages[:trimmed])
        system = self._system_prompt_out()
        if system:
            return [{"role": "system", "content": system}] + msgs
        return msgs
