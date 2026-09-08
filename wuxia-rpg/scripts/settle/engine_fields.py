#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine fields 层(由 engine.py 拆分)。"""
import os, sys
from world import character_ops as co
from common import dao as dq
from world import loadout as lo
from world import mastery as ms
from store import save_manager as sm

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from settle.engine_io import _prefix_role, _read_char, _resolve_party, _write_char

# 遣散机制：玩家主动遣散队友需付遣散费（被遣散者一级属性之和×10）；金钱不足则改扣该 NPC 好感
DISMISS_RELATION_PENALTY = -20   # 玩家金钱不足时，扣被遣散 NPC 的关系度

def _chg_copper(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = co.apply_copper(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _chg_exp(slot, c):
    name = c["角色"]
    party = _resolve_party(slot)
    if name not in party:
        return {"ok": False, "msg": f"经验变更仅限玩家或队伍成员【{name}不在队】，不得给敌方/场外角色加经验"}
    char = _read_char(slot, name)
    if not char:
        return {"ok": False, "msg": f"未找到角色【{name}】"}
    r = co.apply_exp(char, c)
    if r["ok"]:
        _write_char(slot, name, char)
    return _prefix_role(c, r)

def _chg_relation(slot, c):
    # 关系度变更只接受「角色」字段，表示该角色对主角的关系度发生变化。
    # 关系度存于该角色（NPC）的「关系度」字段，与其它变更一致地改「角色」。
    name = c["角色"]
    player = (sm.read_meta(slot) or {}).get("角色名")
    if name == player:
        return {"ok": False, "msg": "关系度变更不可作用于玩家主控（关系度是 NPC 对主角的好感，主控本身无此字段）"}
    npc = _read_char(slot, name)
    if not npc:
        return {"ok": False, "msg": f"未找到角色【{name}】"}
    r = co.apply_relation(npc, c)
    if r["ok"]:
        _write_char(slot, name, npc)
    return _prefix_role(c, r)

def _chg_item(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = lo.apply_item(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _chg_equip(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = lo.apply_equip(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _chg_carry_skill(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = co.apply_carry_skill(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _carry_skill_op(slot, role, action):
    """装/卸/换 携带武学：基于当前携带列表增量修改，复用 apply_carry_skill 落盘。
    操作 装：加一门已习得的主动武学（须未携带、携带未满4）；
    操作 卸：从携带中移除一门；
    操作 换：以一门已习得主动武学替换携带中的另一门。"""
    char = _read_char(slot, role)
    if not char:
        return {"ok": False, "msg": f"未找到角色【{role}】"}
    op = action.get("操作")
    skill = action.get("武学")
    target = action.get("目标武学")
    carried = list(char.get("携带技能") or [])
    learned = {n for n, _ in dq.get_learned_skills_with_level(char)}

    def is_active(name):
        s = dq.get("武学", name)
        return bool(s) and s.get("类型") != "心法"

    if op == "装":
        if not skill:
            return {"ok": False, "msg": "装上武学须传入 武学"}
        if skill not in learned:
            return {"ok": False, "msg": f"未习得武学【{skill}】，无法装上"}
        if not is_active(skill):
            return {"ok": False, "msg": f"【{skill}】为心法，不可携带，仅可运转"}
        if skill in carried:
            return {"ok": False, "msg": f"【{skill}】已在携带中"}
        if len(carried) >= 4:
            return {"ok": False, "msg": "携带武学已达4门上限，请先卸下"}
        new_list = carried + [skill]
        msg = f"装上 {skill}"
    elif op == "卸":
        if not skill:
            return {"ok": False, "msg": "卸下武学须传入 武学"}
        if skill not in carried:
            return {"ok": False, "msg": f"【{skill}】未在携带中"}
        new_list = [s for s in carried if s != skill]
        msg = f"卸下 {skill}"
    elif op == "换":
        if not skill or not target:
            return {"ok": False, "msg": "替换武学须传入 武学 与 目标武学"}
        if target not in carried:
            return {"ok": False, "msg": f"【{target}】未在携带中，无法替换"}
        if skill not in learned:
            return {"ok": False, "msg": f"未习得武学【{skill}】，无法装上"}
        if not is_active(skill):
            return {"ok": False, "msg": f"【{skill}】为心法，不可携带，仅可运转"}
        if skill != target and skill in carried:
            return {"ok": False, "msg": f"【{skill}】已在携带中"}
        new_list = [skill if s == target else s for s in carried]
        msg = f"以 {skill} 替换 {target}"
    else:
        return {"ok": False, "msg": f"未知携带武学操作【{op}】"}
    r = co.apply_carry_skill(char, {"名列表": new_list})
    if r["ok"]:
        _write_char(slot, role, char)
        return {"ok": True, "msg": msg, "变更": f"{role} {msg}"}
    return r

def _chg_carry_item(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = lo.apply_carry_item(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _carry_item_op(slot, role, action):
    """装/卸/换 携带物品（战斗消耗品）：基于当前携带列表增量修改，复用 apply_carry_item 落盘。
    操作 装：加一类战斗消耗品（须物品栏持有、未携带、携带未满4类）；
    操作 卸：从携带中移除一类；
    操作 换：以一类战斗消耗品替换携带中的另一类。"""
    char = _read_char(slot, role)
    if not char:
        return {"ok": False, "msg": f"未找到角色【{role}】"}
    op = action.get("操作")
    item = action.get("物品")
    target = action.get("目标物品")
    carried = list(char.get("携带物品") or [])
    bag = char.get("物品") or []
    bag_set = {it if isinstance(it, str) else (it.get("名称") if isinstance(it, dict) else None)
               for it in bag}

    def is_consumable(name):
        return dq.is_battle_consumable(name)

    if op == "装":
        if not item:
            return {"ok": False, "msg": "装上物品须传入 物品"}
        if item not in bag_set:
            return {"ok": False, "msg": f"物品栏无【{item}】"}
        if not is_consumable(item):
            return {"ok": False, "msg": f"【{item}】非战斗消耗品，不可携带"}
        if item in carried:
            return {"ok": False, "msg": f"【{item}】已在携带中"}
        if len(carried) >= 4:
            return {"ok": False, "msg": "携带物品已达4类上限，请先卸下"}
        new_list = carried + [item]
        msg = f"携带 {item}"
    elif op == "卸":
        if not item:
            return {"ok": False, "msg": "卸下物品须传入 物品"}
        if item not in carried:
            return {"ok": False, "msg": f"【{item}】未在携带中"}
        new_list = [s for s in carried if s != item]
        msg = f"卸下 {item}"
    elif op == "换":
        if not item or not target:
            return {"ok": False, "msg": "替换物品须传入 物品 与 目标物品"}
        if target not in carried:
            return {"ok": False, "msg": f"【{target}】未在携带中，无法替换"}
        if item not in bag_set:
            return {"ok": False, "msg": f"物品栏无【{item}】"}
        if not is_consumable(item):
            return {"ok": False, "msg": f"【{item}】非战斗消耗品，不可携带"}
        if item != target and item in carried:
            return {"ok": False, "msg": f"【{item}】已在携带中"}
        new_list = [item if s == target else s for s in carried]
        msg = f"以 {item} 替换 {target}"
    else:
        return {"ok": False, "msg": f"未知携带物品操作【{op}】"}
    r = lo.apply_carry_item(char, {"名列表": new_list})
    if r["ok"]:
        _write_char(slot, role, char)
        return {"ok": True, "msg": msg, "变更": f"{role} {msg}"}
    return r

def _chg_xinfa(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = co.apply_xinfa(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _chg_yi(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = co.apply_yi(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _chg_party(slot, c):
    name = c["角色"]
    char = _read_char(slot, name)
    if not char:
        return {"ok": False, "msg": f"未找到角色【{name}】"}
    op = c.get("操作")
    # 入队人数校验：含玩家上限 4 人；已在队者重入不视为超员。
    # _resolve_party 事务感知，故同批多次入队也实时累计，确保批量变更强约束。
    if op == "入" and not char.get("在队"):
        party = _resolve_party(slot)
        if name not in party and len(party) >= 4:
            return {"ok": False, "msg": "队伍已满（上限4人，含玩家）", "变更": ""}
    # 离队遣散：玩家主动遣散需付遣散费（被遣散者一级属性之和×10），金钱不足则扣 NPC 好感
    extra = ""
    if op == "离" and c.get("原因") == "遣散":
        player = (sm.read_meta(slot) or {}).get("角色名")
        pc = _read_char(slot, player) if player else None
        if pc:
            base = char.get("一级属性") or {}
            fee = sum(int(v) for v in base.values()) * 10
            copper = int(pc.get("铜钱", pc.get("银两", 0)) or 0)
            if copper >= fee:
                pc["铜钱"] = copper - fee
                _write_char(slot, player, pc)
                extra = f"，付遣散费{fee}铜钱"
            else:
                # 金钱不足：扣被遣散 NPC 好感
                rel = co.apply_relation(char, {"值": DISMISS_RELATION_PENALTY})
                extra = f"，金钱不足{rel['变更']}({name}好感下降)"
        # 玩家不存在则仅正常离队
    r = co.apply_party(char, c)
    if r["ok"]:
        _write_char(slot, name, char)
    out = {"ok": r["ok"], "msg": f"{name} {r['msg']}{extra}", "变更": f"{name} {r['变更']}{extra}"}
    if r["ok"]:
        out["_在队变更"] = c  # 供 settle 收集同步队伍
    return out

def _chg_hp(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = co.apply_hp(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _chg_mp(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = co.apply_mp(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _chg_death(slot, c):
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    r = co.apply_death(char, c)
    if r["ok"]:
        _write_char(slot, c["角色"], char)
    return _prefix_role(c, r)

def _apply_mastery(slot, c):
    """武学精进/秘籍习得：调 mastery 纯函数，合并 delta 后写回。"""
    char = _read_char(slot, c["角色"])
    if not char:
        return {"ok": False, "msg": f"未找到角色【{c['角色']}】"}
    skill = c["名"]
    if c["操作"] == "精进":
        r = ms.advance(char, skill)
    else:  # 习得(秘籍)
        r = ms.book_advance(char, skill)
    if not r["ok"]:
        return {"ok": False, "msg": r["msg"]}
    delta = r["delta"]
    for k, v in delta.items():
        char[k] = v
    _write_char(slot, c["角色"], char)
    return {"ok": True, "msg": r["msg"], "变更": f"{c['角色']} {r['msg']}",
            "消耗经验": r.get("消耗经验"), "剩余经验": r.get("剩余经验"), "新等级": r.get("新等级")}

# 变更分发表：类型 -> (原语函数, 是否需槽位重定向已在settle统一做)
_FIELD_HANDLERS = {
    "铜钱": _chg_copper, "经验": _chg_exp, "关系度": _chg_relation, "物品": _chg_item,
    "装备": _chg_equip, "携带技能": _chg_carry_skill, "携带物品": _chg_carry_item,
    "运转心法": _chg_xinfa, "技艺": _chg_yi, "在队": _chg_party,
    "气血": _chg_hp, "内力": _chg_mp, "死亡": _chg_death,
}

