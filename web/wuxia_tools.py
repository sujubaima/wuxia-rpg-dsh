"""从共享 Tools Schema 构造 Web agent-lite 的最小权限工具集。"""

import os

from engine_client import EngineClientError

REFERENCE_LIMIT = 200_000
WEB_SKILL_USAGE_NOTE = (
    "- 指令中的相对引用路径均相对于该技能目录；\n"
    "- 阅读 references 下的规则文档时使用 wuxia_read_reference；\n"
    "- 所有结算、判定与查询均使用对应 wuxia_* 工具，不要尝试运行脚本或访问其他文件。"
)


def build_wuxia_registry(client, manifest, skill_dir):
    """注册 manifest 中的引擎工具及受限引用读取工具。"""
    from core.tools import Tool, ToolRegistry

    tools = manifest.get("tools") if isinstance(manifest, dict) else None
    if not isinstance(tools, list) or not tools:
        raise ValueError("Tools Schema 缺少 tools")
    registry = ToolRegistry()

    for spec in tools:
        name = spec.get("name")
        operation = spec.get("operation")
        description = spec.get("description")
        parameters = spec.get("input_schema")
        if not all(isinstance(v, str) and v for v in (name, operation, description)):
            raise ValueError("Tools Schema 存在无效工具定义")
        if not isinstance(parameters, dict):
            raise ValueError(f"{name} 缺少 input_schema")

        def invoke(_operation=operation, **payload):
            try:
                return client.call_operation(_operation, payload)
            except EngineClientError as exc:
                return {"错误": str(exc), "错误代码": exc.code}

        registry.register(Tool(name, description, parameters, invoke))

    references_dir = os.path.realpath(os.path.join(skill_dir, "references"))

    def read_reference(path):
        if not isinstance(path, str) or not path.strip():
            return {"错误": "path 须为非空字符串"}
        rel = path.strip().replace("\\", "/")
        if rel.startswith("./"):
            rel = rel[2:]
        if rel.startswith("references/"):
            rel = rel[len("references/"):]
        candidate = os.path.realpath(os.path.join(references_dir, rel))
        if candidate != references_dir and not candidate.startswith(references_dir + os.sep):
            return {"错误": "仅允许读取 references 目录"}
        if not candidate.lower().endswith(".md"):
            return {"错误": "仅允许读取 Markdown 引用文档"}
        if not os.path.isfile(candidate):
            return {"错误": f"引用文档不存在: {rel}"}
        with open(candidate, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(REFERENCE_LIMIT + 1)
        return {
            "path": "references/" + os.path.relpath(candidate, references_dir).replace(os.sep, "/"),
            "content": content[:REFERENCE_LIMIT],
            "truncated": len(content) > REFERENCE_LIMIT,
        }

    registry.register(Tool(
        "wuxia_read_reference",
        "读取武侠RPG Skill references 目录中的 Markdown 规则文档。路径须相对于 Skill 根目录或 references 目录，不能读取其他文件。",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "description": "如 references/rules/wuxia-rpg-combat.md"},
            },
            "required": ["path"],
        },
        read_reference,
    ))
    return registry
