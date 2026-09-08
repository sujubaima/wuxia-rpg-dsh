#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""角色纯字段变更 业务逻辑库 —— 纯函数，就地改角色 dict，不落盘。

供 explore.settle 调用：explore 负责 read_char / write_char 落盘，
本模块只负责角色单字段改动的校验与计算（铜钱/经验/关系度/气血/内力/技艺/
运转心法/携带技能/在队）。

与 loadout（物品/装备）、mastery（武学）并列，同属"内存变更层"。

接口契约：每个函数 (char, change) -> {"ok": bool, "msg": str, "变更": str}，
成功时 char 已就地修改好，调用方据此写回。失败 ok=False 且不动 char。
关系度例外：作用于"目标 NPC"，apply_relation 改的是传入的目标 char。

依赖：仅 dao（运转心法校验武学类型用）。slot 路径/落盘由调用方负责。
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from common import dao as dq

YI_KEYS = ("音律", "弈棋", "诗书", "绘画", "医术", "博物")
YI_CAP = 25


def resolve_delta(c):
    """兼容两种写法：按 `值` 正负（推荐），或 `操作` 加/减 配合正 `值`。
    `操作` 为 `减` 且 `值` 为正时取反；既有符号优先以符号为准。"""
    val = int(c.get("值", 0))
    if c.get("操作") == "减" and val > 0:
        val = -val
    return val


def _zero_err(label):
    """增量变更传入 0 值的统一报错——值无意义，须 GM 改非 0 或取消该条目。"""
    return {"ok": False, "msg": f"{label}变更目前传入0值，请GM重新斟酌更换成非0值或取消该变更"}


def apply_copper(char, c):
    """铜钱增减，不低于 0。兼容旧档「银两」字段。"""
    delta = resolve_delta(c)
    if delta == 0:
        return _zero_err("铜钱")
    old = char.get("铜钱", char.get("银两", 0)) or 0
    char["铜钱"] = max(0, old + delta)
    sign = "+" if delta >= 0 else ""
    return {"ok": True, "msg": f"铜钱 {old}→{char['铜钱']}", "变更": f"铜钱{sign}{delta}"}


def apply_exp(char, c):
    """经验值增减，不低于 0。"""
    delta = resolve_delta(c)
    if delta == 0:
        return _zero_err("经验")
    old = char.get("经验值", 0) or 0
    char["经验值"] = max(0, old + delta)
    sign = "+" if delta >= 0 else ""
    return {"ok": True, "msg": f"经验值 {old}→{char['经验值']}", "变更": f"经验{sign}{delta}"}


def apply_relation(target_char, c):
    """关系度增减，作用于目标 NPC，clamp(0,100)。调用方负责读/写目标角色。"""
    delta = resolve_delta(c)
    if delta == 0:
        return _zero_err("关系度")
    old = target_char.get("关系度", 50)
    target_char["关系度"] = max(0, min(100, old + delta))
    sign = "+" if delta >= 0 else ""
    return {"ok": True, "msg": f"关系度 {old}→{target_char['关系度']}", "变更": f"关系度{sign}{delta}"}


def apply_hp(char, c):
    """气血 设/加，受气血上限封顶、不低于 0。"""
    op = c.get("操作", "加")
    val = int(c.get("值", 0))
    if op != "设" and val == 0:
        return _zero_err("气血")
    cap = char.get("气血上限", 0) or 0
    old = char.get("气血", 0) or 0
    newv = val if op == "设" else max(0, old + val)
    if cap:
        newv = min(newv, cap)
    char["气血"] = newv
    return {"ok": True, "msg": f"气血 {old}→{newv}", "变更": f"气血{newv}"}


def apply_mp(char, c):
    """内力 设/加，受内力上限封顶、不低于 0。"""
    op = c.get("操作", "加")
    val = int(c.get("值", 0))
    if op != "设" and val == 0:
        return _zero_err("内力")
    cap = char.get("内力上限", 0) or 0
    old = char.get("内力", 0) or 0
    newv = val if op == "设" else max(0, old + val)
    if cap:
        newv = min(newv, cap)
    char["内力"] = newv
    return {"ok": True, "msg": f"内力 {old}→{newv}", "变更": f"内力{newv}"}


def apply_yi(char, c):
    """技艺单项增减，clamp(0, YI_CAP)。"""
    key = c["名"]
    if key not in YI_KEYS:
        return {"ok": False, "msg": f"非法技艺【{key}】"}
    delta = int(c.get("值", 0))
    if delta == 0:
        return _zero_err("技艺")
    yi = char.setdefault("技艺", {k: 0 for k in YI_KEYS})
    old = yi.get(key, 0)
    newv = max(0, min(YI_CAP, old + delta))
    yi[key] = newv
    sign = "+" if delta >= 0 else ""
    return {"ok": True, "msg": f"{key} {old}→{newv}", "变更": f"{key}{sign}{delta}"}


def apply_xinfa(char, c):
    """设运转心法：校验已习得且类型=心法，'无'则卸下。"""
    name = c["名"]
    if name and name != "无":
        learned = {w.get("名称") for w in char.get("武学", []) if isinstance(w, dict)}
        if name not in learned:
            return {"ok": False, "msg": f"尚未习得【{name}】"}
        skill = dq.get("武学", name)
        if not skill or skill.get("类型") != "心法":
            return {"ok": False, "msg": f"【{name}】非心法"}
    char["运转心法"] = None if name in ("无", "", None) else name
    return {"ok": True, "msg": f"运转心法={char['运转心法']}", "变更": f"运转心法 {char['运转心法'] or '无'}"}


def apply_carry_skill(char, c):
    """设战斗携带武学列表（≤4 门）。"""
    lst = c.get("名列表") or []
    if len(lst) > 4:
        return {"ok": False, "msg": "携带技能不得超过4门"}
    char["携带技能"] = list(lst)
    return {"ok": True, "msg": f"携带技能={lst}", "变更": "配置携带技能"}


def apply_party(char, c):
    """入/离队，设 `在队` 字段。"""
    op = c["操作"]  # 入/离
    if op == "入":
        char["在队"] = True
        return {"ok": True, "msg": "入队", "变更": "入队"}
    char["在队"] = False
    return {"ok": True, "msg": "离队", "变更": "离队"}


def apply_death(char, c):
    """标记死亡（处决）：置 死亡=true。死亡为终态，不支持复活。"""
    char["死亡"] = True
    return {"ok": True, "msg": "死亡", "变更": "死亡"}
