"""Skill (技能) 管理: 供 Agent 识别和按需加载的能力包。

设计: 系统提示词中只注入各 Skill 的名称 + 一句话简介,
模型判断需要某项技能时调用 use_skill 工具, 将完整指令注入上下文,
避免长系统提示词占满窗口。这和 Claude Code 的 Skill 机制一致。

支持从目录加载技能文件, 见 SkillRegistry.load_dir。
"""

import os
from dataclasses import dataclass


@dataclass
class Skill:
    name: str
    description: str   # 一句话简介, 出现在系统提示词的技能清单里
    instructions: str  # 完整指令, use_skill 加载后注入上下文
    base_dir: str = ""  # 技能文件所在目录, 指令中的相对路径基于此目录解析


class SkillRegistry:
    def __init__(self):
        self._skills = {}

    def register(self, skill: Skill):
        self._skills[skill.name] = skill

    def names(self):
        return list(self._skills)

    def get(self, name):
        return self._skills.get(name)

    def build_prompt_section(self):
        """生成系统提示词中的技能清单部分。"""
        if not self._skills:
            return ""
        lines = ["## 可用技能 (Skills)", "",
                 "你可以使用以下技能。当任务需要某个技能时, 先调用 use_skill 工具加载其完整指令, 再按指令行动:", ""]
        for s in self._skills.values():
            lines.append(f"- **{s.name}**: {s.description}")
        return "\n".join(lines)

    # ---------- 从目录加载 ----------

    def load_dir(self, directory):
        """从目录加载技能, 支持两种布局:

        1. Claude Code 风格:  <dir>/<skill-name>/SKILL.md   (一个子目录一个技能)
        2. 扁平 .md 文件:     <dir>/<skill-name>.md

        文件格式:
            ---
            name: my-skill          # 可选, 默认取目录名/文件名
            description: 一句话简介  # 可选, 默认取正文第一行
            ---
            完整指令正文 (use_skill 加载后注入上下文)

        返回注册成功的技能名列表。
        """
        loaded = []
        if not os.path.isdir(directory):
            return loaded
        for entry in sorted(os.listdir(directory)):
            path = os.path.join(directory, entry)
            if os.path.isdir(path):
                skill_file = os.path.join(path, "SKILL.md")
                fallback = entry
                base_dir = os.path.abspath(path)
            elif entry.endswith(".md") and not entry.startswith("."):
                skill_file = path
                base_dir = os.path.abspath(directory)
                fallback = entry[:-3]
                # 顶层 SKILL.md: 传入的就是技能根目录本身, 名字取目录名而非 "SKILL"
                if fallback == "SKILL":
                    fallback = os.path.basename(os.path.abspath(directory))
            else:
                continue
            if not os.path.isfile(skill_file):
                continue
            if self._load_file(skill_file, fallback, base_dir):
                loaded.append(fallback)
        return loaded

    def _load_file(self, path, fallback_name, base_dir=""):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        meta, body = _parse_frontmatter(text)
        body = body.strip()
        if not body:
            return False
        name = meta.get("name") or fallback_name
        description = meta.get("description") or next(
            (line.strip() for line in body.splitlines() if line.strip()), name)
        self.register(Skill(name=name, description=description,
                            instructions=body, base_dir=base_dir))
        return True


def _parse_frontmatter(text):
    """解析 --- 包裹的 name:/description: 头, 返回 (meta, body)。无头部则原样返回。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, parts[2]


# ---------------- 内置示例技能 ----------------

def register_builtin_skills(registry: SkillRegistry):
    registry.register(Skill(
        name="python-helper",
        description="Python 编程任务: 代码编写、审查、调试规范。",
        instructions=(
            "你获得了 python-helper 技能, 进行 Python 任务时遵守:\n"
            "1. 优先标准库, 引入第三方库前先确认必要性;\n"
            "2. 代码要附简要注释并处理边界/异常情况;\n"
            "3. 修改已有代码前先 read 阅读上下文, 保持风格一致;\n"
            "4. 给出代码后用 calculator 或推演验证关键计算路径。"
        ),
    ))
    registry.register(Skill(
        name="file-inspector",
        description="文件/目录探索: 阅读项目结构、定位代码位置。",
        instructions=(
            "你获得了 file-inspector 技能:\n"
            "1. 先用 list 逐层查看目录结构, 不要盲目猜测路径;\n"
            "2. 对关键文件用 read 阅读, 注意 truncated 标记, 大文件分段读;\n"
            "3. 汇总时说明文件间的依赖关系。"
        ),
    ))
