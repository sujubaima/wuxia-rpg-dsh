"""工具 (Tool) 注册与执行, 并提供一组内置工具。

每个 Tool 描述为 OpenAI function 格式, 模型通过 tool_calls 发起调用,
Agent 解析参数后执行本地 handler 并回传结果 (tool 消息)。
"""

import ast
import datetime
import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable

    def to_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def tool(self, name, description, parameters=None):
        """装饰器用法: @registry.tool(...)"""
        def deco(fn):
            self.register(Tool(name, description, parameters or
                               {"type": "object", "properties": {}}, fn))
            return fn
        return deco

    def getSchemas(self):
        return [t.to_schema() for t in self._tools.values()]

    def names(self):
        return list(self._tools)

    def execute(self, name, arguments_json):
        """执行工具, 任何错误都转为字符串结果返回给模型 (不让循环崩溃)。"""
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
        try:
            args = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"参数解析失败: {e}"}, ensure_ascii=False)
        if not isinstance(args, dict):
            return json.dumps({"error": "参数必须是 JSON 对象"}, ensure_ascii=False)
        try:
            result = tool.handler(**args)
            return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001 - 工具错误要反馈给模型而不是抛出
            return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


# ---------------- 内置工具 ----------------

# read 去重缓存: (绝对路径, max_chars) -> (mtime_ns, size)。
# 同一文件未改动时重复 read 只回轻量提示, 不再塞全文进上下文。
# 注意: 会话历史被压缩/裁剪/清空时必须调 clear_read_cache(),
# 否则模型拿到的"见上文"提示所指内容已不在上下文里。
_READ_CACHE = {}


def clear_read_cache():
    _READ_CACHE.clear()

def _safe_eval(expr):
    """基于 AST 白名单的安全四则运算。"""
    ops = {
        ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
        ast.Pow: lambda a, b: a ** b, ast.Mod: lambda a, b: a % b,
        ast.USub: lambda a: -a,
    }

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.operand))
        raise ValueError(f"不支持的表达式: {ast.dump(node)}")

    return ev(ast.parse(expr, mode="eval"))


def register_builtin_tools(registry: ToolRegistry):
    @registry.tool(
        name="get_current_time",
        description="获取当前日期和时间 (本地时区)。",
    )
    def get_current_time():
        now = datetime.datetime.now()
        return {
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
            "timestamp": int(now.timestamp()),
        }

    @registry.tool(
        name="calculator",
        description="计算数学表达式, 支持 + - * / ** % 和括号, 例如 '3.14 * 2 ** 10'。",
        parameters={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "要计算的数学表达式"},
            },
            "required": ["expression"],
        },
    )
    def calculator(expression):
        return {"expression": expression, "result": _safe_eval(expression)}

    @registry.tool(
        name="read",
        description="读取本地文本文件内容 (1M 字符以内直接全部读取, 超过 1M 的文件用 max_chars 分段读)。同一文件未改动时重复读取只会返回轻量提示, 内容以上次读取为准。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "max_chars": {"type": "integer", "description": "最多读取字符数, 默认 1000000, 上限 1000000"},
            },
            "required": ["path"],
        },
    )
    def read_file(path, max_chars=1000000):
        max_chars = min(max(int(max_chars), 1), 1_000_000)
        abspath = os.path.abspath(path)
        key = (abspath, max_chars)
        # 以 (mtime_ns, size) 为指纹, 文件被任何方式改动过都会失配, 照常返回全文
        try:
            st = os.stat(abspath)
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None
        if stamp is not None and _READ_CACHE.get(key) == stamp:
            # 缓存命中：仍返回完整内容（而非只说 unchanged），避免模型用 bash cat 补读
            with open(abspath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(max_chars + 1)
            return {
                "path": abspath,
                "content": content[:max_chars],
                "truncated": len(content) > max_chars,
                "cached": True,
            }
        with open(abspath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(max_chars + 1)  # 多读 1 个字符判断是否截断
        truncated = len(content) > max_chars
        if stamp is not None:
            _READ_CACHE[key] = stamp
        return {"path": abspath, "content": content[:max_chars], "truncated": truncated}

    @registry.tool(
        name="write",
        description="把文本写入文件 (覆盖写, 自动创建父目录)。要新建或整体替换文件用它; 局部修改请用 bash。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的完整文本内容"},
            },
            "required": ["path", "content"],
        },
    )
    def write_file(path, content):
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"path": os.path.abspath(path), "chars": len(content)}

    @registry.tool(
        name="list",
        description="列出目录下的文件和子目录。",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目录路径, 默认当前目录"}},
        },
    )
    def list_files(path="."):
        entries = sorted(os.listdir(path))
        return {"path": os.path.abspath(path), "entries": entries}

    @registry.tool(
        name="bash",
        description="执行本地 shell 命令 (如运行技能脚本, 如 python3 scripts/xxx.py)。可经 stdin 传数据, cwd 指定工作目录。stdout 超过 12000 字符会被截断。",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "stdin": {"type": "string", "description": "可选, 传给命令的标准输入内容"},
                "cwd": {"type": "string", "description": "可选, 工作目录, 技能脚本应设为技能根目录"},
                "timeout": {"type": "integer", "description": "超时秒数, 默认 60, 上限 300"},
            },
            "required": ["command"],
        },
    )
    def run_command(command, stdin=None, cwd=None, timeout=60):
        timeout = min(max(int(timeout or 60), 1), 300)
        try:
            proc = subprocess.run(
                command, shell=True, input=stdin,
                cwd=cwd or None, timeout=timeout,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return {"error": f"命令执行超时({timeout}s)", "command": command}
        stdout = proc.stdout
        if len(stdout) > 12000:
            stdout = stdout[:12000] + f"\n...(输出截断, 共 {len(proc.stdout)} 字符)"
        return {
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": proc.stderr[-4000:] if proc.stderr else "",
        }
