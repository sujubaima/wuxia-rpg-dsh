"""Agent 主循环: 接收用户输入 -> 模型推理 -> 工具调用 -> 直到产出最终回复。"""

from .client import ChatClient, ContextOverflowError
from .session import Session
from .skills import SkillRegistry, register_builtin_skills
from .tools import ToolRegistry, register_builtin_tools, clear_read_cache


DEFAULT_SYSTEM = (
    "你是一个通用 AI 助手 Agent。\n"
    "工作方式:\n"
    "1. 分析问题, 需要外部信息或计算时主动调用工具, 不要编造数据;\n"
    "2. 一次可以调用多个互相独立的工具;\n"
    "3. 任务需要特定技能时先用 use_skill 加载; 完成时直接给出最终回答。\n"
)
DEFAULT_SKILL_USAGE_NOTE = (
    "- 指令中的相对路径 (如 ./references/xxx.md, scripts/xxx.py) 均相对于该目录;\n"
    "- 阅读技能文档: 用 read 读取绝对路径;\n"
    "- 运行技能脚本: 用 bash 并将 cwd 设为该目录。"
)


class Agent:
    def __init__(self, client=None, tools=None, skills=None,
                 system_prompt=None, max_iterations=100, max_context_tokens=1_000_000,
                 skill_dirs=None, reasoning_effort="high", skill_usage_note=None):
        self.client = client or ChatClient()
        # 主循环推理强度 (压缩摘要的 _summarize 调用不带, 省 token)
        self.reasoning_effort = reasoning_effort
        self.tools = tools or ToolRegistry()
        self.skills = skills or SkillRegistry()

        # 技能必须在构建系统提示词之前加载, 否则清单里看不到, 不会被触发
        for d in skill_dirs or []:
            self.skills.load_dir(d)

        # use_skill 是框架内置工具, 允许模型按需加载技能指令
        @self.tools.tool(
            name="use_skill",
            description="加载指定技能的完整指令。参数为技能名, 返回该技能的详细指令。",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "技能名称"}},
                "required": ["name"],
            },
        )
        def use_skill(name):
            skill = self.skills.get(name)
            if skill is None:
                return {"error": f"未知技能: {name}", "available": self.skills.names()}
            result = {"skill": skill.name, "instructions": skill.instructions}
            if skill.base_dir:
                result["base_dir"] = skill.base_dir
                usage_note = (DEFAULT_SKILL_USAGE_NOTE
                              if skill_usage_note is None else skill_usage_note)
                result["instructions"] += (
                    f"\n\n---\n[使用须知] 本技能根目录: {skill.base_dir}\n"
                    + usage_note
                )
            return result

        prompt = (system_prompt if system_prompt is not None
                  else DEFAULT_SYSTEM + "\n" + self.skills.build_prompt_section())
        self.session = Session(system_prompt=prompt, max_context_tokens=max_context_tokens,
                               summarizer=self._summarize)
        # 历史被压缩/裁剪丢弃后, 旧 read 结果已不在上下文, 去重缓存必须失效
        self.session.on_drop = lambda dropped: clear_read_cache()
        self.max_iterations = max_iterations

    # ---------- 上下文压缩 ----------

    _SUMMARIZE_SYSTEM = (
        "你是上下文压缩器。把给定的早期对话压缩为不超过 500 字的中文事实清单。\n"
        "保留: 用户的任务目标与偏好、关键事实与数值、已做的决定、工具执行的重要结果"
        "(文件路径/错误原因/游戏存档slot/剧情与状态变更等)。\n"
        "丢弃: 礼节性对话、中间推理过程、已在摘要中失效的过时事实。\n"
        "若给出旧摘要, 把其中仍然生效的事实合并进新摘要。只输出摘要正文, 不要任何前后缀。"
    )

    def _summarize(self, dropped, prev_summary):
        """Session 回调: 压缩早期消息为摘要 (供下次拼装 system 前缀)。"""
        lines = []
        for m in dropped:
            role = m.get("role")
            content = m.get("content") or ""
            if m.get("tool_calls"):
                names = ", ".join(tc["function"]["name"] for tc in m["tool_calls"])
                content += f" [调工具: {names}]"
            if len(content) > 500:
                content = content[:500] + "...(截断)"
            lines.append(f"{role}: {content}")
        user = "早期对话:\n" + "\n".join(lines)
        if prev_summary:
            user = "旧摘要(合并其中仍生效的事实):\n" + prev_summary + "\n\n" + user
        reply = self.client.chat(
            messages=[
                {"role": "system", "content": self._SUMMARIZE_SYSTEM},
                {"role": "user", "content": user},
            ],
            max_tokens=1024,
        )
        return (reply.get("content") or "").strip()

    @classmethod
    def with_builtins(cls, **kwargs):
        """内置工具 + 内置技能的便捷构造。"""
        tools = ToolRegistry()
        register_builtin_tools(tools)
        skills = SkillRegistry()
        register_builtin_skills(skills)
        return cls(tools=tools, skills=skills, **kwargs)

    def step(self, verbose=False):
        """执行一轮 推理->工具调用, 返回 assistant message; 无工具调用时即最终回复。"""
        # 上下文超限时: 压缩历史后自动重试, 最多 3 次
        message = None
        for attempt in range(1, 4):
            try:
                message = self.client.chat(
                    messages=self.session.get_messages(),
                    tools=self.tools.getSchemas(),
                    reasoning_effort=self.reasoning_effort,
                )
                break
            except ContextOverflowError as err:
                if attempt >= 3:
                    raise
                shrunk = self.session.force_compress()
                if verbose:
                    print(f"[上下文超限] {err}... 已压缩历史, 第 {attempt} 次重试")
                if not shrunk:
                    if attempt >= 2:
                        raise  # 压缩不了什么, 无救, 放弃此轮由 run() 兜底文案
                    # 首次无无可压缩(单条消息就超)时, 强行丢弃最老消息组
                    drop = min(2, len(self.session.messages))
                    dropped_msgs = self.session.messages[:drop]
                    self.session.messages = self.session.messages[drop:]
                    if self.session.summarizer:
                        try:
                            self.session.summary = self.session.summarizer(dropped_msgs, self.session.summary)
                        except Exception:
                            pass
                    clear_read_cache()
        self.session.add_assistant(message)

        if verbose and message.get("reasoning_content"):
            print(f"[思考] {message['reasoning_content'][:300]}")

        for tc in message.get("tool_calls") or []:
            fn = tc["function"]
            result = self.tools.execute(fn["name"], fn.get("arguments") or "")
            if verbose:
                print(f"[工具] {fn['name']}({fn.get('arguments') or ''}) -> {result[:200]}")
            self.session.add_tool(tc["id"], fn["name"], result)

        return message

    def run(self, user_input, verbose=False):
        """处理一轮用户请求, 返回最终文本回复。"""
        self.session.add_user(user_input)
        for _ in range(self.max_iterations):
            message = self.step(verbose=verbose)
            if not message.get("tool_calls"):
                return message.get("content") or ""
        return "(已达到最大工具调用轮数, 未能完成请求, 请换个方式描述或拆分任务。)"

    def reset(self):
        self.session.clear()
        clear_read_cache()
