"""会话上下文管理: 维护消息历史, 超限先压缩为摘要, 兜底才裁剪。"""

import json

# use_skill 不算过程性工具调用: 历史与压缩均豁免, 技能指令是持久上下文
SKILL_TOOL = "use_skill"
# 历史拼接始终保留的工具名: use_skill 压缩亦豁免;
# wuxia_read_reference (规则文档为持久参考) 仅历史豁免, 压缩照常
HISTORY_KEEP_TOOLS = frozenset({SKILL_TOOL, "wuxia_read_reference"})


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


def _normalize_tool_messages(messages):
    """移除不完整或错配的 tool_calls 组，保证导出历史满足消息协议。"""
    kept = []
    dropped = []
    i = 0
    while i < len(messages):
        message = messages[i]
        if message.get("role") == "tool":
            dropped.append(message)
            i += 1
            continue
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            kept.append(message)
            i += 1
            continue

        j = i + 1
        results = []
        while j < len(messages) and messages[j].get("role") == "tool":
            results.append(messages[j])
            j += 1
        call_ids = [call.get("id") for call in message["tool_calls"]]
        result_ids = [result.get("tool_call_id") for result in results]
        complete = (
            call_ids
            and all(call_ids)
            and len(call_ids) == len(set(call_ids))
            and len(result_ids) == len(call_ids)
            and set(result_ids) == set(call_ids)
        )
        group = [message, *results]
        (kept if complete else dropped).extend(group)
        i = j
    return kept, dropped


def _skill_calls_of(message):
    """返回 assistant 消息 tool_calls 中的 use_skill 调用。"""
    if message.get("role") != "assistant":
        return []
    return [c for c in message.get("tool_calls") or []
            if c.get("function", {}).get("name") == SKILL_TOOL]


def _skill_call_name(call):
    """从 use_skill 调用参数解析技能名, 失败返回 None。"""
    try:
        return json.loads(call["function"].get("arguments") or "{}").get("name")
    except ValueError:
        return None


def _extract_skill_calls(messages):
    """提取 use_skill 调用及其结果, 返回 ([(call, result), ...], 其余消息)。
    其余消息保持原序, 混合调用的 assistant 只留下未提取的调用; 无结果的调用不提取。"""
    taken_calls = []
    rest = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        skill_calls = _skill_calls_of(msg)
        if not skill_calls:
            rest.append(msg)
            i += 1
            continue
        j = i + 1
        results = []
        while j < len(messages) and messages[j].get("role") == "tool":
            results.append(messages[j])
            j += 1
        by_id = {r.get("tool_call_id"): r for r in results}
        taken = [c for c in skill_calls if c.get("id") in by_id]
        taken_ids = {c.get("id") for c in taken}
        taken_calls.extend((dict(c), dict(by_id[c["id"]])) for c in taken)
        remaining = [c for c in msg["tool_calls"] if c.get("id") not in taken_ids]
        if remaining:
            leftover = dict(msg)
            leftover["tool_calls"] = remaining
            rest.append(leftover)
        elif (msg.get("content") or "").strip():
            leftover = dict(msg)
            leftover.pop("tool_calls", None)
            rest.append(leftover)
        rest.extend(r for r in results if r.get("tool_call_id") not in taken_ids)
        i = j
    return taken_calls, rest


class Session:
    def __init__(self, system_prompt="", max_context_tokens=1_000_000,
                 summarizer=None, compress_target_ratio=0.5,
                 include_thinking=False, include_tools=False,
                 compress_thinking=False, compress_tools=False):
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
        # 历史轮 (最后一条 user 之前) 导出时是否拼接 thinking / 工具调用内容;
        # 当前轮始终完整保留 (工具调用协议要求), 原始存储不受影响
        self.include_thinking = include_thinking
        self.include_tools = include_tools
        # 压缩摘要输入是否包含 thinking / 工具调用内容 (与拼接开关相互独立)
        self.compress_thinking = compress_thinking
        self.compress_tools = compress_tools
        # messages 只含对话消息, system 在导出时拼接
        self.messages = []
        # 早期历史的压缩摘要, 拼接在 system 之后
        self.summary = ""
        # 历史被压缩/裁剪时提取出的 use_skill 调用 (call, result), 导出时拼回头部
        self.skill_calls = []

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
        self.skill_calls = []

    # ---------- token 估算 ----------

    def _message_tokens(self, msg):
        tokens = _estimate_tokens(msg.get("content") or "")
        if msg.get("reasoning_content"):
            tokens += _estimate_tokens(msg["reasoning_content"])
        for tc in msg.get("tool_calls") or []:
            tokens += _estimate_tokens(tc["function"].get("arguments") or "")
        return tokens

    def _total_tokens(self):
        return (_estimate_tokens(self.system_prompt)
                + _estimate_tokens(self.summary)
                + sum(self._message_tokens(m) for m in self.messages)
                + sum(self._message_tokens(r) for _, r in self.skill_calls))

    # ---------- 压缩与裁剪 ----------

    def _add_skill_calls(self, entries):
        """持久化提取出的 use_skill 调用, 按 call id 去重。"""
        known = {call.get("id") for call, _ in self.skill_calls}
        for call, result in entries:
            if call.get("id") not in known:
                self.skill_calls.append((call, result))
                known.add(call.get("id"))

    def drop_head(self, n):
        """应急丢弃存储头部 n 条消息。use_skill 调用提取保留, 其余消息返回供摘要。"""
        head = self.messages[:n]
        self.messages = self.messages[n:]
        entries, rest = _extract_skill_calls(head)
        self._add_skill_calls(entries)
        return rest

    def _normalize_history(self):
        kept, dropped = _normalize_tool_messages(self.messages)
        if not dropped:
            return
        self.messages = kept
        if self.on_drop:
            self.on_drop(dropped)

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
        """核心: 按组选前缀, use_skill 提取保留, 其余 summarizer 压成摘要, 移除原消息。
        返回是否真的进行了压缩。"""
        groups, kept = self._drop_groups(target_tokens)
        if not groups:
            return False
        dropped = [m for g in groups for m in g]
        entries, dropped = _extract_skill_calls(dropped)
        self._add_skill_calls(entries)
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
        self._normalize_history()
        if self._total_tokens() <= self.max_context_tokens:
            return
        target = int(self.max_context_tokens * self.compress_target_ratio)
        self._compress_to(target)

    def force_compress(self, ratio=0.5):
        """API 报上下文超限时主动压缩: 无视预算, 把历史压到当前的 ratio 比例。
        返回是否确实有内容被压缩 (无可压内容时重试也是白压, 应放弃)。"""
        self._normalize_history()
        target = max(1, int(self._total_tokens() * ratio))
        return self._compress_to(target)

    def _system_prompt_out(self):
        if self.summary:
            return (self.system_prompt + "\n\n"
                    "## 早期对话摘要 (已压缩的历史, 其中事实仍然有效)\n"
                    + self.summary)
        return self.system_prompt

    def _strip_history(self, msgs):
        """按开关裁剪历史轮 (最后一条 user 之前) 的 thinking 与工具调用内容。
        返回新列表, 不修改原始消息; 当前轮原样保留。"""
        cut = len(msgs)
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") == "user":
                cut = i
                break
        out = []
        for msg in msgs[:cut]:
            if (msg.get("role") == "tool"
                    and not (self.include_tools or msg.get("name") in HISTORY_KEEP_TOOLS)):
                continue
            msg = dict(msg)
            if not self.include_thinking:
                msg.pop("reasoning_content", None)
            if msg.get("tool_calls") and not self.include_tools:
                # 豁免工具只剥非豁免调用, 混合调用保留豁免部分
                keep = [c for c in msg["tool_calls"]
                        if c.get("function", {}).get("name") in HISTORY_KEEP_TOOLS]
                if keep:
                    msg["tool_calls"] = keep
                else:
                    msg.pop("tool_calls", None)
                    if not (msg.get("content") or "").strip():
                        continue  # 纯工具调用消息剥离后为空, 整条丢弃
            out.append(msg)
        return out + msgs[cut:]

    def _splice_skill_calls(self, msgs):
        """把持久化的 use_skill 调用拼回消息头部; 仍在消息里的跳过, 同名技能以最新加载为准。"""
        if not self.skill_calls:
            return msgs
        present_ids = set()
        loaded = set()
        for m in msgs:
            for c in _skill_calls_of(m):
                present_ids.add(c.get("id"))
                name = _skill_call_name(c)
                if name:
                    loaded.add(name)
        # 存储时序为旧->新, 倒序遍历让最新加载优先占住技能名
        picked = []
        seen = set(loaded)
        for call, result in reversed(self.skill_calls):
            if call.get("id") in present_ids:
                continue
            name = _skill_call_name(call)
            if name:
                if name in seen:
                    continue
                seen.add(name)
            picked.append((call, result))
        if not picked:
            return msgs
        picked.reverse()
        return ([{"role": "assistant", "content": "",
                  "tool_calls": [c for c, _ in picked]}]
                + [r for _, r in picked] + msgs)

    def get_messages(self):
        """导出完整 messages (含 system 与历史摘要)。超限先压缩, 兜底再裁剪;
        历史轮的 thinking / 工具调用内容按开关剥离, 当前轮始终完整。"""
        self._normalize_history()
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
        if trimmed:
            # 兜底裁剪只影响导出视图, use_skill 调用先提取持久化再裁
            entries, _ = _extract_skill_calls(self.messages[:trimmed])
            self._add_skill_calls(entries)
            if self.on_drop:
                self.on_drop(self.messages[:trimmed])
        msgs = self._strip_history(msgs)
        msgs = self._splice_skill_calls(msgs)
        system = self._system_prompt_out()
        if system:
            return [{"role": "system", "content": system}] + msgs
        return msgs
