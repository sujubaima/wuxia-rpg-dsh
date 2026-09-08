"""agent-lite: 一个简单的通用 AI Agent。

特性:
- 会话上下文管理 (Session): 历史消息维护 + 自动裁剪
- 工具识别与调用 (ToolRegistry + builtin tools): OpenAI tool_calls 协议
- Skill 识别与按需加载 (SkillRegistry): 系统提示词注入技能摘要, use_skill 工具按需加载
"""

from .agent import Agent
from .session import Session
from .tools import Tool, ToolRegistry
from .skills import Skill, SkillRegistry

__all__ = ["Agent", "Session", "Tool", "ToolRegistry", "Skill", "SkillRegistry"]
