#!/usr/bin/env python3
"""agent-lite 入口: 交互式 REPL, 也支持单发提问。

用法:
  python3 main.py                              # 交互模式 (默认自动加载 ./skills)
  python3 main.py "现在几点?"                  # 单次提问
  python3 main.py --skills-dir ./my_skills     # 加载技能目录
  python3 main.py --skills-dir ./my_skills "问题"
  AGENT_API_BASE=... AGENT_MODEL=... python3 main.py

REPL 命令:
  /reset    清空会话上下文
  /history  查看当前消息数
  /tools    列出已注册工具
  /skills   列出已注册技能
  /exit     退出
"""

import os
import sys

from core import Agent
from core.config import apply_llm_env


def repl(agent):
    print("agent-lite 已启动 (模型: %s)" % agent.client.model)
    print("输入问题开始对话, /exit 退出, /help 查看命令。\n")
    while True:
        try:
            line = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            print("再见!")
            break
        if line == "/reset":
            agent.reset()
            print("会话已清空。")
            continue
        if line == "/history":
            n = len(agent.session.messages)
            tk = sum(agent.session._message_tokens(m) for m in agent.session.messages)
            print(f"共 {n} 条消息, 估算 {tk} tokens。")
            continue
        if line == "/tools":
            print("工具:", ", ".join(agent.tools.names()))
            continue
        if line == "/skills":
            print("技能:", ", ".join(agent.skills.names()))
            continue
        if line == "/help":
            print("命令: /reset /history /tools /skills /exit")
            continue
        try:
            answer = agent.run(line, verbose=True)
        except Exception as e:  # noqa: BLE001
            print(f"出错: {e}\n")
            continue
        print(f"\nAgent > {answer}\n")


def main():
    argv = sys.argv[1:]

    # 读取根目录 config.json 填充 AGENT_API_BASE / AGENT_API_TOKEN / AGENT_MODEL
    # (环境变量已设则保留, 配置仅补缺)
    apply_llm_env()

    skills_dir = None
    if "--skills-dir" in argv:
        i = argv.index("--skills-dir")
        if i + 1 >= len(argv):
            print("--skills-dir 需要一个目录路径", file=sys.stderr)
            sys.exit(1)
        skills_dir = argv[i + 1]
        del argv[i:i + 2]
    # 未显式指定时, 若当前目录存在 ./skills 则自动加载
    if skills_dir is None and os.path.isdir("./skills"):
        skills_dir = "./skills"

    # 技能目录必须在 Agent 构造时传入, 在构建 system prompt 之前加载, 否则无法被触发
    agent = Agent.with_builtins(skill_dirs=[skills_dir] if skills_dir else None)
    if skills_dir:
        print(f"已加载技能: {', '.join(agent.skills.names())}", file=sys.stderr)

    if argv:
        print(agent.run(" ".join(argv), verbose=True))
    else:
        repl(agent)


if __name__ == "__main__":
    main()
