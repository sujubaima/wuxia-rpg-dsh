#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""武学精进（十境）引擎 —— 展示十境表与执行精进。

用法：
  python3 scripts/mastery.py table  <角色名> <武学名> [当前经验值] [当前等级]
  python3 scripts/mastery.py advance <角色名> <武学名> [当前经验值] [当前等级]
  python3 scripts/mastery.py book-advance <角色名> <武学名> [--slot <N>]

- 角色与武学经 dao 统一读取（assets/data/characters、assets/data/skills）。
- 可选的"当前经验值/当前等级"用于覆盖预设值（对接 GM 在线状态）；
  缺省时从角色预设读取（经验值字段、武学列表中该武学的等级，未习得视为 0 级）。
- table：打印十境表，标注已习得/未习得，并提示下一境所需经验与是否可精进。
- advance：校验经验是否足够，足够则输出精进结果（新经验、新等级、增量JSON），
  不直接落盘——由 GM 据返回的增量写入存档。
- book-advance：秘籍复用精进——未习得则习得 1 级，已习得则精进一层（**不消耗经验**，
  消耗的是秘籍本身），已达第 10 境则无法使用（退出码 1）。输出精进结果与增量JSON
  （武学列表整体替换），不落盘，由 GM 据增量 write-char 并在大世界消耗秘籍。

精进消耗（升至第 n 级，n=2..10）：
  cost(n) = round(640 × (n−1)^0.7 × tier_mult)
  tier_mult = 1 + 0.25 × 品级   （品级取武学"品级"字段，null/缺省视为 0）
  即品级 0→×1.0、1→×1.25、2→×1.5、3→×1.75；品级越高，精进越贵。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from common import dao as dq  # noqa: E402


def tier_mult(skill):
    """武学品级系数：1 + 0.25×品级，null/缺省视为 0。"""
    tier = skill.get("品级")
    if tier is None:
        tier = 0
    return 1 + 0.25 * tier


def cost_to_reach(n, skill):
    """升至第 n 级所需经验（n>=2），含品级系数。

    base(n) = 640 × (n-1)^0.7（幂律，压头尾差距；品级0满级约 17191）
    """
    base = round(640 * (n - 1) ** 0.7)
    mult = tier_mult(skill)
    val = base * mult
    return int(round(val))


def load_char(name):
    char = dq.get("角色", name)
    return dict(char) if char else None


def get_learned_level(char, skill_name):
    """从角色武学列表取该武学等级；未习得返回 0。"""
    for w in char.get("武学", []):
        if isinstance(w, dict) and w.get("名称") == skill_name:
            return w.get("等级", 1) or 1
    return 0


def fmt_effect(eff, skill=None, level=None):
    """把单条等级增益的"效果"字典格式化为可读文字。
    效果中可有 "特效增强" 键承载该境的特殊机制描述（纯展示用，执行逻辑仍在 effect 脚本）。
    遇 "解锁特效" 时附带该武学技能特效的一句话描述（经 dao.describe_skill_effect 折算当前等级）。"""
    if not eff:
        return "（无增益）"
    parts = []
    jingxiao = None
    has_unlock = False
    for k, v in eff.items():
        if k == "特效增强":
            jingxiao = v
            continue
        if k == "武艺" and isinstance(v, dict):
            parts.append("、".join(f"武艺·{wk} {sign(vv)}{vv}" for wk, vv in v.items()))
        elif k == "解锁特效":
            has_unlock = True
            parts.append("解锁特效")
        elif isinstance(v, bool):
            parts.append(f"{k} {'开' if v else '关'}")
        else:
            parts.append(f"{k} {sign(v)}{fmt_num(v)}")
    if has_unlock and skill is not None:
        # 解锁特效所在境即特效上线之境，按该等级折算描述
        desc = dq.describe_skill_effect(skill.get("技能特效", ""), skill, level or 1)
        if desc:
            # 「解锁特效」与描述合并为「解锁特效：{描述}」
            idx = parts.index("解锁特效")
            parts[idx] = f"解锁特效：{desc}"
    text = "；".join(parts)
    if jingxiao:
        text = f"{text}、{jingxiao}" if text else str(jingxiao)
    return text


def sign(v):
    return "+" if (isinstance(v, (int, float)) and v >= 0) else ""


def fmt_num(v):
    if isinstance(v, float):
        # 0.05 -> 0.05；0.1 -> 0.1
        return f"{v:g}"
    return str(v)


def _tier_rows(skill, skill_name, cur_exp, cur_level):
    """计算十境表每境的结构化数据（build_table 文本版与 build_table_struct 共享同源）。
    返回 (rows, meta)：
      rows: [{境, 状态, 已习得, 当前, 下一境, 消耗经验, 增益}]（1~10 境）
      meta: {品级, 品级系数, 当前境, 经验, 下一境, 下一境消耗, 可精进, 心法}
    """
    table = skill.get("等级增益", []) or []
    by_level = {e.get("等级", 1): e for e in table if isinstance(e, dict)}
    learned = cur_level >= 1
    next_level = cur_level + 1 if learned else 1
    is_xinfa = skill.get("类型") == "心法"
    xinfa_desc = dq.xinfa_effect(skill, 1) if is_xinfa else ""
    rows = []
    for lv in range(1, 11):
        entry = by_level.get(lv)
        eff = (entry or {}).get("效果", {}) if entry else {}
        if lv == 1 and not eff:
            eff_txt = "习得武学"
        else:
            eff_txt = fmt_effect(eff, skill, lv)
        if lv == 1 and xinfa_desc:
            eff_txt = f"{eff_txt}；{xinfa_desc}"
        if is_xinfa:
            unlocks = dq.xinfa_unlock_at(skill, lv)
            if unlocks:
                eff_txt = f"{eff_txt}；运转时施加" + "、".join(unlocks)
        cost = 0 if lv <= 1 else cost_to_reach(lv, skill)
        rows.append({
            "境": lv,
            "已习得": lv <= cur_level,
            "当前": lv == cur_level,
            "下一境": lv == next_level,
            "消耗经验": cost,
            "增益": eff_txt,
        })
    if cur_level >= 10:
        can = False
        need = None
    else:
        need = cost_to_reach(next_level, skill)
        can = cur_exp >= need
    meta = {
        "品级": skill.get("品级"),
        "品级系数": tier_mult(skill),
        "当前境": cur_level if learned else 0,
        "经验": cur_exp,
        "下一境": None if cur_level >= 10 else next_level,
        "下一境消耗": need,
        "可精进": can,
        "心法": is_xinfa,
    }
    return rows, meta


def build_table(char, skill_name, cur_exp, cur_level):
    skill = dq.get("武学", skill_name)
    if not skill:
        return None, f"未找到武学【{skill_name}】（经 dao 未找到）"

    rows, meta = _tier_rows(skill, skill_name, cur_exp, cur_level)
    learned = cur_level >= 1
    next_level = meta["下一境"]

    lines = []
    tier = meta["品级"]
    tier_txt = f"品级{tier}" if tier is not None else "品级未定"
    mult = meta["品级系数"]
    lines.append(f"【{skill_name}】十境表　{tier_txt}（精进消耗×{mult:g}）　当前第 {meta['当前境']} 境　经验 {cur_exp}")
    lines.append("")
    lines.append(f"{'境':>3}  {'状态':<8}  {'消耗经验':>6}  增益")
    lines.append("-" * 60)
    for r in rows:
        status = "✓ 已习得" if r["已习得"] else "✗ 未习得"
        mark = "（当前）" if r["当前"] else ("  ← 下一境" if r["下一境"] else "")
        cost_txt = "—" if r["境"] <= 1 else str(r["消耗经验"])
        lines.append(f"{r['境']:>3}  {status:<8}  {cost_txt:>6}  {r['增益']}{mark}")

    lines.append("-" * 60)
    if cur_level >= 10:
        lines.append("已达大成（第 10 境），无可精进之境。")
    else:
        need = meta["下一境消耗"]
        can = meta["可精进"]
        lines.append(f"下一境（第 {next_level} 境）需经验 {need}　当前 {cur_exp}　"
                     f"{'可精进' if can else '经验不足，暂无法精进'}")
    return lines, meta["可精进"]


def build_table_struct(char, skill_name, cur_exp, cur_level):
    """结构化十境表（WEB_UI 用）：返回 dict 或 None（武学未找到时第二返回值为错误信息）。
    与 build_table 同源（共享 _tier_rows），供前端按字段渲染卡片/表格。"""
    skill = dq.get("武学", skill_name)
    if not skill:
        return None, f"未找到武学【{skill_name}】（经 dao 未找到）"
    rows, meta = _tier_rows(skill, skill_name, cur_exp, cur_level)
    return {
        "武学": skill_name,
        "类型": skill.get("类型"),
        "十境": rows,
        **meta,
    }, meta["可精进"]



def cmd_table(args):
    name, skill_name, exp, lvl = parse_args(args)
    char = load_char(name)
    if not char:
        print(f"未找到角色【{name}】（经 dao 未找到）")
        return
    if exp is None:
        exp = char.get("经验值", 0)
    if lvl is None:
        lvl = get_learned_level(char, skill_name)
    if not dq.get("武学", skill_name):
        print(f"未找到武学【{skill_name}】（经 dao 未找到）")
        return
    if lvl == 0:
        print(f"【{name}】尚未习得【{skill_name}】，无法精进。")
        print("提示：可在世界中对角色使用对应秘籍《<武学名>》以习得。")
        return
    lines, _ = build_table(char, skill_name, exp, lvl)
    if isinstance(lines, str):
        print(lines)
    else:
        print("\n".join(lines))


def advance(char, skill_name, exp=None, lvl=None):
    """武学精进（纯函数）：校验经验/等级/十境上限，生成增量，不落盘不打印。

    char: 角色 dict（含 经验值、武学 列表）。skill_name: 武学名。
    exp/lvl 可选覆盖（缺省从角色取）。返回 {"ok":bool,"delta":{...},"msg":"..",
    "消耗经验":N,"新等级":N,"剩余经验":N}。成功 delta 含 经验值(替换) 与 武学(整体替换)；
    失败 ok=False 无 delta。
    """
    if not char:
        return {"ok": False, "msg": "未找到角色"}
    exp = char.get("经验值", 0) if exp is None else exp
    lvl = get_learned_level(char, skill_name) if lvl is None else lvl
    skill = dq.get("武学", skill_name)
    if not skill:
        return {"ok": False, "msg": f"未找到武学【{skill_name}】"}
    if lvl == 0:
        return {"ok": False, "msg": f"尚未习得【{skill_name}】，无法精进"}
    if lvl >= 10:
        return {"ok": False, "msg": f"【{skill_name}】已达大成（第 10 境），无可精进"}
    next_level = lvl + 1
    need = cost_to_reach(next_level, skill)
    if exp < need:
        return {"ok": False, "msg": f"经验不足：升至第 {next_level} 境需 {need}，当前 {exp}"}
    new_exp = exp - need
    new_wx = []
    for w in char.get("武学", []):
        if isinstance(w, dict) and w.get("名称") == skill_name:
            new_wx.append({"名称": skill_name, "等级": next_level})
        else:
            new_wx.append(w)
    delta = {"经验值": new_exp, "武学": new_wx}
    return {"ok": True, "delta": delta,
            "msg": f"【{skill_name}】第 {lvl} 境 → 第 {next_level} 境",
            "消耗经验": need, "新等级": next_level, "剩余经验": new_exp}


def book_advance(char, skill_name, lvl=None):
    """秘籍习得/精进（纯函数）：未习得→1级；已习得→+1级；大成→拒。不落盘不打印。

    lvl 可选覆盖（缺省从角色武学列表取）。返回 {"ok":bool,"delta":{"武学":[...]},
    "msg":"..","新等级":N,"动作":"习得"/"精进"}。失败 ok=False 无 delta。
    """
    if not char:
        return {"ok": False, "msg": "未找到角色"}
    if not dq.get("武学", skill_name):
        return {"ok": False, "msg": f"未找到武学【{skill_name}】"}
    lvl = get_learned_level(char, skill_name) if lvl is None else lvl
    if lvl >= 10:
        return {"ok": False, "msg": f"【{skill_name}】已达大成（第 10 境），秘籍无法再精进"}
    new_level = 1 if lvl == 0 else lvl + 1
    new_wx, found = [], False
    for w in char.get("武学", []):
        if isinstance(w, dict) and w.get("名称") == skill_name:
            new_wx.append({"名称": skill_name, "等级": new_level})
            found = True
        else:
            new_wx.append(w)
    if not found:
        new_wx.append({"名称": skill_name, "等级": new_level})
    action = "习得" if lvl == 0 else "精进"
    return {"ok": True, "delta": {"武学": new_wx},
            "msg": f"【{skill_name}】{action} → 第 {new_level} 境",
            "新等级": new_level, "动作": action}


def cmd_advance(args):
    name, skill_name, exp, lvl = parse_args(args)
    char = load_char(name)
    if not char:
        print(f"未找到角色【{name}】（经 dao 未找到）")
        return
    if exp is not None:
        char["经验值"] = exp
    result = advance(char, skill_name, exp=exp, lvl=lvl)
    if not result["ok"]:
        print(result["msg"])
        return
    print(f"精进成功：{result['msg']}")
    print(f"消耗经验 {result['消耗经验']}　剩余经验 {result['剩余经验']}")
    print("增量JSON：")
    print(json.dumps(result["delta"], ensure_ascii=False))


def cmd_book_advance(args):
    """秘籍复用精进（CLI）：调纯函数 book_advance 并打印。成功返回 0，失败返回 1。"""
    name, skill_name, _exp, lvl = parse_args(args)
    char = load_char(name)
    if not char:
        print(f"未找到角色【{name}】（经 dao 未找到）")
        return 1
    result = book_advance(char, skill_name, lvl=lvl)
    if not result["ok"]:
        print(result["msg"])
        return 1
    print(f"秘籍生效：【{name}】{result['msg']}")
    print("增量JSON：")
    print(json.dumps(result["delta"], ensure_ascii=False))
    return 0


def parse_args(args):
    """[角色名, 武学名, 经验值?, 等级?]，后两项可选覆盖。"""
    name = args[0] if len(args) > 0 else None
    skill = args[1] if len(args) > 1 else None
    exp = int(args[2]) if len(args) > 2 and args[2] is not None else None
    lvl = int(args[3]) if len(args) > 3 and args[3] is not None else None
    return name, skill, exp, lvl


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    # 抽取 --slot <N>：正式游戏数据从 slot 的 .data/ 工作副本读取
    slot_arg = None
    filtered = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--slot" and i + 1 < len(argv):
            slot_arg = int(argv[i + 1])
            i += 2
            continue
        filtered.append(a)
        i += 1
    if slot_arg is not None:
        dq.set_slot(slot_arg)
    argv = filtered

    cmd = argv[0]
    rest = argv[1:]
    if cmd == "table":
        cmd_table(rest)
    elif cmd == "advance":
        cmd_advance(rest)
    elif cmd == "book-advance":
        return cmd_book_advance(rest)
    else:
        print(f"未知子命令：{cmd}（可用：table / advance / book-advance）")


if __name__ == "__main__":
    main()
