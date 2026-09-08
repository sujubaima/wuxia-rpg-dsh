# agent-lite

一个简单通用的 AI Agent(纯 Python 标准库,无第三方依赖)。

## 特性

- **会话上下文管理**(`core/session.py`)
  - 上限 1M (估算 token); 超限先掉模型压缩历史成摘要钉在 system 前缀, 兜有才裁剪
  - `assistant(tool_calls)` 与 `tool` 结果始终同组, 不产生孤立 tool 消息
- **工具识别与调用**(`core/tools.py`)
  - OpenAI 兼容 `tool_calls` 协议, 装饰器一行注册新工具
  - 内置: `get_current_time`、`calculator`(AST 安全求值)、`read`、`write`、`list`、`bash`(执行技能脚本, 支持 stdin/cwd/超时)
  - ⚠️ `bash` 让模型可以执行任意 shell 命令(shell=True, 无沙箱), 仅限本地可信环境调试; 生产使用请自行加白名单/审批
  - 工具/参数错误不外抛, 转为错误消息回传给模型, 让 Agent 自行纠错
- **Skill 识别与按需加载**(`core/skills.py`)
  - 系统提示词只注入技能名 + 简介, 模型通过 `use_skill` 工具按需拉取完整指令, 节省上下文
  - 内置示例技能: `python-helper`、`file-inspector`

## 快速开始

```bash
python3 main.py               # 交互式 REPL
python3 main.py "现在几点?"   # 单次提问
```

模型接口默认走 `api_demo` 中的服务, 可用环境变量覆盖:

```bash
AGENT_API_BASE="https://your-openai-compatible-endpoint.example/v1" AGENT_MODEL="your-model" python3 main.py
```

REPL 命令: `/reset` 清空会话, `/history` 查看消息数, `/tools` 列工具, `/skills` 列技能, `/exit` 退出。

## 技能目录 (Skills)

把你的技能目录传给 Agent 即可被识别和触发:

```bash
python3 main.py --skills-dir ./my_skills         # 显式指定
python3 main.py                                  # 未指定时自动加载 ./skills
```

支持两种布局, 兼容 Claude Code 风格:

```
my_skills/
├── code-review/SKILL.md  # 子目录 + SKILL.md
└── git-helper.md         # 或扁平 .md 文件
```

文件格式 (frontmatter 可选, 缺省时 name 取目录/文件名, description 取正文第一行):

```markdown
---
name: code-review
description: 审查代码变更: 按统一规范输出评审报告。
---
当任务与代码评审相关时:
1. 先复述变更意图;
2. 按"正确性/可读性/性能/风险"四段输出;
...
```

触发是模型自主完成的: 系统提示词里常驻技能名 + description, 模型判断用户请求与某个技能相关时,
调用 `use_skill` 工具拉取完整 instructions 注入上下文, 然后按指令执行。**description 是触发的关键**,
要写清楚"这个技能在什么场景下用"。条件不满足时它不会触发, 也不需要手动指定。

编程方式加载: `Agent.with_builtins(skill_dirs=["./my_skills"])`。

**注意时序**: 技能目录必须在构造 Agent 时传入 (或构造前加载到 registry), 因为
system prompt 中的技能清单是在 `Agent.__init__` 里生成的。`agent = Agent(...)` 之后
再调 `agent.skills.load_dir(...)` 注册的技能不会出现在提示词里, **无法被触发**。
带脚本/文档的技能 (相对路径引用 references/scripts) 会自动携带技能根目录,
`use_skill` 加载时告知模型用绝对路径读文档、用 `bash`(cwd=技能根目录) 跑脚本。

## 扩展

```python
from core import Agent, ToolRegistry, Skill, SkillRegistry

tools = ToolRegistry()

@tools.tool(name="echo", description="原样返回输入文本",
            parameters={"type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"]})
def echo(text):
    return text

skills = SkillRegistry()
skills.register(Skill(name="my-skill", description="...", instructions="..."))

agent = Agent(tools=tools, skills=skills)
print(agent.run("你好"))
```

## 架构

```
用户输入 -> Session.add_user
         -> ChatClient.chat(messages=Session.get_messages(), tools=ToolRegistry.getSchemas())
            [get_messages 时: 估算 token > 上限 -> 模型压缩最老消息为摘要钉入 system -> 极端情况兜底裁剪]
            [服务端报上下文超限 (ContextOverflowError) -> Session.force_compress(压到 50%) -> 自动重试, 最多 3 次]
         -> 若返回 tool_calls: 逐个执行工具, 结果以 tool 消息写回 Session, 继续循环
         -> 若无 tool_calls: 返回最终回复
(最多 max_iterations=100 轮工具调用; 上下文上限 1M 估算 token)
```
