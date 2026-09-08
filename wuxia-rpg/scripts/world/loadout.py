#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物品/装备/携带物品 业务逻辑库 —— 纯函数，就地改角色 dict，不落盘。

供 explore.settle 调用：explore 负责 read_char / write_char 落盘，
本模块只负责物品增减、装备穿脱、携带物品配置的业务校验与字段改动。

变更条目类型（与 explore 分发表对应）：
  - 物品   增/减：背包增减；减时背包不足自动从装备槽补足，归零则联动清理携带配置
  - 装备   穿/脱：装备槽穿脱，原槽位装备退回物品栏
  - 携带物品 设：设战斗携带消耗品种类列表（≤4 类）

接口契约：每个函数 (char, change) -> {"ok": bool, "msg": str, "变更": str}，
成功时 char 已就地修改好，调用方据此写回。失败 ok=False 且不动 char。

依赖：仅 dao（is_equipment 判断装备类）。slot 路径/落盘由调用方（explore）负责。
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from common import dao as dq

# 五个装备槽位（与 explore.EQUIP_SLOTS 同源，定义在此供本模块自洽）
EQUIP_SLOTS = ("武器1", "武器2", "护甲", "饰品", "冠巾")


def sync_loadout_after_removal(char, item=None, slot=None):
    """移除物品/装备后联动清理携带配置与对应装备槽，避免引用已失物。
    - item：若该物在 `携带物品` 中则移出；若正占据某装备槽则卸空（被劫/损毁场景）。
    - slot：仅清理指定槽位（脱下不联动携带物品）。
    返回被清理的描述片段。"""
    notes = []
    equip = char.get("装备", {}) or {}
    if item:
        for s in EQUIP_SLOTS:
            if equip.get(s) == item:
                equip[s] = None
                notes.append(f"卸空{s}")
    elif slot and slot in EQUIP_SLOTS:
        if equip.get(slot):
            equip[slot] = None
            notes.append(f"卸空{slot}")
    if item:
        carry = char.get("携带物品", []) or []
        if item in carry:
            char["携带物品"] = [x for x in carry if x != item]
            notes.append("移出携带物品")
    return "、".join(notes)


def apply_item(char, c):
    """物品增减。char 就地修改，返回 {ok, msg, 变更}。"""
    item = c["名"]
    n = int(c.get("数量", 1))
    inv = char.setdefault("物品", [])
    equip = char.get("装备", {}) or {}
    # 增减均校验物品库存在定义
    if not dq.get("物品", item):
        return {"ok": False, "msg": f"未找到物品【{item}】，物品库无此定义"}
    if c["操作"] == "增":
        inv.extend([item] * n)
        return {"ok": True, "msg": f"物品+{item}×{n}", "变更": f"获得 {item}×{n}"}
    # 减：持有量含背包 + 各装备槽中正穿着的同名件
    in_inv = inv.count(item)
    equipped_slots = [s for s in EQUIP_SLOTS if equip.get(s) == item]
    total = in_inv + len(equipped_slots)
    if total < n:
        return {"ok": False, "msg": f"物品【{item}】不足（含装备中共{total}，需{n}）"}
    # 先从背包扣
    for _ in range(min(n, in_inv)):
        inv.remove(item)
    # 不足部分从装备槽卸下并移除
    need_from_equip = n - in_inv
    for s in equipped_slots[:need_from_equip]:
        equip[s] = None
    # 联动：该物彻底归零后，清理携带物品配置
    note = ""
    if item not in inv and not any(equip.get(s) == item for s in EQUIP_SLOTS):
        note = sync_loadout_after_removal(char, item=item)
        if note:
            note = f"（{note}）"
    return {"ok": True, "msg": f"物品-{item}×{n}{note}", "变更": f"失去 {item}×{n}"}


def apply_equip(char, c):
    """装备穿脱。char 就地修改，返回 {ok, msg, 变更}。"""
    equip = char.setdefault("装备", {})
    inv = char.setdefault("物品", [])
    if c["操作"] == "穿":
        item = c["名"]
        s = c.get("槽位")
        if s not in EQUIP_SLOTS:
            return {"ok": False, "msg": f"非法槽位【{s}】"}
        if not dq.is_equipment(item):
            return {"ok": False, "msg": f"【{item}】非装备类"}
        if item not in inv:
            return {"ok": False, "msg": f"物品栏无【{item}】"}
        old = equip.get(s)
        inv.remove(item)
        if old:
            inv.append(old)  # 原槽位退回物品栏
        equip[s] = item
        return {"ok": True, "msg": f"装备{item}→{s}", "变更": f"装备 {item}（{s}）"}
    # 脱
    s = c.get("槽位")
    if s not in EQUIP_SLOTS:
        return {"ok": False, "msg": f"非法槽位【{s}】"}
    old = equip.get(s)
    if not old:
        return {"ok": False, "msg": f"{s}无装备"}
    inv.append(old)
    equip[s] = None
    return {"ok": True, "msg": f"卸下{old}（{s}）", "变更": f"卸下 {old}（{s}）"}


def apply_carry_item(char, c):
    """设战斗携带消耗品种类列表（≤4 类）。char 就地修改，返回 {ok, msg, 变更}。"""
    lst = c.get("名列表") or []
    if len(lst) > 4:
        return {"ok": False, "msg": "携带物品不得超过4类"}
    char["携带物品"] = list(lst)
    return {"ok": True, "msg": f"携带物品={lst}", "变更": "配置携带物品"}
