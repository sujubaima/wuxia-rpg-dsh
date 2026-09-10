#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine 端 Markdown UI 渲染层。

20 个确定性界面的完整 Markdown 由 engine 按 references/ui/ 各文档模板直接拼接，
GM 只原样透传 `渲染文本`，不再自行筛选字段组装或润色战报。

模式规则（WUXIA_RPG_RENDER_MODULE，经 common.render_mode 归一，未设置=LLM）：
- dsh：目标 UI 固定 `渲染文本=""`（前端卡片消费结构化字段，不重复出正文）；
- 其余模式（LLM/WEB_UI/…）：按模板生成完整 Markdown。

judge 的 exploration-ui+错误 是 GM 自检信号，不生成玩家界面文本。
"""
from common import dao as dq
from common.render_mode import is_dsh_mode, render_mode

# 引擎直出 Markdown 的界面白名单
MARKDOWN_UI_IDS = frozenset({
    "title-ui", "exploration-ui", "save-ui", "exploration-battle-ui", "battle-ui", "battle-end-ui",
    "wuxue-ui", "equip-ui", "item-ui", "mastery-ui", "character-ui", "bag-ui",
    "travel-ui", "inn-ui", "wuxue-list-ui", "trade-buy-ui", "trade-sell-ui",
    "message-ui", "map-ui", "clue-ui",
})


# ----------------------------- 共享格式化 -----------------------------

def _s(v, default=""):
    """None → 缺省；其余 str() 化。"""
    if v is None:
        return default
    return str(v)


def _txt(v, default=""):
    """叙事文本归一：字面 \\n 换回真实换行并去首尾空白。

    judge 入参字符串不得含裸换行，GM 常以字面 \\n 断段，落盘后即成两个字符；
    渲染时须还原为真实换行，否则整段挤成一行。"""
    return _s(v, default).replace("\\n", "\n").strip()


def _money(v):
    """铜钱数 → 文案：不足千「X钱」，满千「X两X钱」。"""
    n = int(v or 0)
    if abs(n) < 1000:
        return f"{n}钱"
    sign = "-" if n < 0 else ""
    n = abs(n)
    return f"{sign}{n // 1000}两{n % 1000}钱"


def _pct(v):
    """比例 0.2 → 「20%」。"""
    try:
        return f"{round(float(v) * 100):g}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_ts(ts):
    """存档时间戳 YYYYMMDD_HHMMSS → 「年/月/日 时:分:秒」；其余原样。"""
    s = _s(ts)
    date, _, clock = s.partition("_")
    if len(date) == 8 and len(clock) == 6 and date.isdigit() and clock.isdigit():
        return f"{date[:4]}/{date[4:6]}/{date[6:]} {clock[:2]}:{clock[2:4]}:{clock[4:]}"
    return s


def _join_vals(v):
    """数组值顿号连接；单值原样（背包筛选说明等用）。"""
    if isinstance(v, (list, tuple)):
        return "、".join(_s(x) for x in v)
    return _s(v)


def _names(v):
    """名单数组 → 顿号连接字符串；元素可为 str 或 {名称}。"""
    if not isinstance(v, (list, tuple)):
        return _s(v)
    out = []
    for x in v:
        out.append(_s(x.get("名称") if isinstance(x, dict) else x))
    return "、".join(x for x in out if x)


def _settle_lines(resp):
    """结算数组 → 反引号高亮的变更行（一行一条，仅取非空 变更）。"""
    out = []
    for r in resp.get("结算") or []:
        if isinstance(r, dict) and r.get("变更"):
            out.append(f"`{r['变更']}`")
    return out


def _cooldown(w):
    """冷却 0 → 「无」。"""
    cd = w.get("冷却时间", 0) or 0
    return "无" if not cd else _s(cd)


def _effect_row(e):
    """效果行（全角空格开头）：　效果：{摘要}。"""
    return f"　效果：{_effect_summary(e.get('使用效果'))}"


_BUFF_NAME_CACHE = None


def _buff_name(buff_id):
    """状态 id → 名称（如 huichun → 回春）；查不到回退 id。"""
    global _BUFF_NAME_CACHE
    if _BUFF_NAME_CACHE is None:
        _BUFF_NAME_CACHE = {}
        try:
            for name, rec in (dq.load_all("状态") or {}).items():
                if isinstance(rec, dict) and rec.get("id"):
                    _BUFF_NAME_CACHE[rec["id"]] = name
        except Exception:
            pass
    return _BUFF_NAME_CACHE.get(buff_id, buff_id)


def _effect_summary(effect):
    """使用效果 dict → 一句话摘要（item-ui 效果列）。

    回复气血/内力直接写数值；施加状态写持续回合；时序保留正负号；
    净化/削减/延长写明数量；多项顿号连接；无效果显示「—」。"""
    if not isinstance(effect, dict) or not effect:
        return "—"
    parts = []
    for key in ("回复气血", "回复内力", "回复体力"):
        if effect.get(key) is not None:
            parts.append(f"{key}{_s(effect[key])}")
    st = effect.get("施加状态")
    if isinstance(st, dict):
        txt = f"施加{_buff_name(st.get('id'))}"
        if st.get("回合") is not None:
            txt += f"（{st['回合']}回合）"
        parts.append(txt)
    if effect.get("时序") is not None:
        try:
            parts.append(f"时序{int(effect['时序']):+d}")
        except (TypeError, ValueError):
            parts.append(f"时序{_s(effect['时序'])}")
    for key in ("净化", "削减", "延长"):
        if effect.get(key) is not None:
            parts.append(f"{key}{_s(effect[key])}")
    tech = effect.get("技艺")
    if isinstance(tech, dict):
        for k, v in tech.items():
            parts.append(f"技艺{k}+{v}")
    return "、".join(parts) if parts else "—"


def _grade(e):
    """品名（品级只显示品名，无则 —）。"""
    return e.get("品名") or "—"


def _sub_or_dash(e):
    return e.get("子类型") or "—"


# ----------------------------- 各界面 renderer -----------------------------

def _head(resp):
    """exploration/exploration-battle 共用抬头。"""
    pos = _s(resp.get("当前位置"))
    seg = _s(resp.get("时段"))
    tim = _s(resp.get("时间"))
    return f"### 【{pos}】 {seg} {tim}　距下次自动存档 {_s(resp.get('剩余'))} 轮"


def _render_exploration(resp):
    b = [_head(resp)]
    plot = _txt(resp.get("剧情描写"))
    if plot:
        b += ["", plot]
    changes = _settle_lines(resp)
    if changes:
        b += ["", "\n".join(changes)]
    elements = resp.get("场景要素") or []
    if elements:
        b += ["", "周围情况"]
        for e in elements:
            sub = _s(e.get("主体"))
            desc = _txt(e.get("描写"))
            b.append(f"- {sub}（{desc}）" if desc else f"- {sub}")
    b += ["", "相邻出口"]
    exits = resp.get("相邻出口") or []
    if exits:
        for x in exits:
            b.append(f"- {_s(x.get('方位'))}（通往{_s(x.get('邻场景'))}）")
    else:
        b.append("- （无）")
    b += ["", f"当前队伍　体力{_s(resp.get('体力'))}　金钱{_money(resp.get('金钱'))}"]
    for row in resp.get("队伍状态") or []:
        b.append(f"- `{_s(row.get('名称'))}` "
                 f"气血({_s(row.get('气血'))}/{_s(row.get('气血上限'))}) "
                 f"内力({_s(row.get('内力'))}/{_s(row.get('内力上限'))})")
    b += ["", "请输入指令（前往地点、与角色对话、观察场景、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_exploration_battle(resp):
    b = [_head(resp)]
    plot = _txt(resp.get("剧情描写"))
    if plot:
        b += ["", plot]
    changes = _settle_lines(resp)
    if changes:
        b += ["", "\n".join(changes)]
    b += ["", "战局双方",
          f"我方：{_names(resp.get('我方'))}",
          f"敌方：{_names(resp.get('敌方'))}"]
    descs = {"玩家角色": None, "我方全员": "操控我方所有角色",
             "AI自动": "我方全由 AI 操控，玩家观战至战斗结束"}
    b += ["", "操控方式"]
    for opt in resp.get("操控选项") or []:
        if opt == "玩家角色":
            b.append(f"- 玩家角色：仅操控 {_s(resp.get('主控'))}")
        else:
            b.append(f"- {_s(opt)}：{_s(descs.get(opt))}")
    b += ["", "请输入指令（选择操控方式、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _title_hint(resp):
    hint = _txt(resp.get("校验提示"))
    return ["", f"✗ {hint}"] if hint else []


def _render_title_home(resp):
    saves = resp.get("存档列表") or []
    logo = """██╗    ██╗██╗   ██╗██╗  ██╗
██║    ██║██║   ██║╚██╗██╔╝
██║ █╗ ██║██║   ██║ ╚███╔╝
██║███╗██║██║   ██║ ██╔██╗
╚███╔███╔╝╚██████╔╝██╔╝ ██╗
 ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═╝

        ── 武 侠 R P G ──"""
    b = ["```text", logo, "```", "", "江湖路远，剑未出鞘。少侠，从何而起？", "",
         f"作者：可乐酸橙　版本：v{_s(resp.get('版本'), '0.0.0')}　存档：{len(saves)}个"]
    b += _title_hint(resp)
    b += ["", "请输入指令（创建角色、读取存档）："]
    return "\n".join(b)


def _render_title_saves(resp):
    b = ["### 【读取存档】"]
    shown = False
    for slot in resp.get("存档列表") or []:
        if not isinstance(slot, dict) or not slot.get("saves"):
            continue
        shown = True
        b += ["", f"【Slot_{_s(slot.get('slot'))} {_s(slot.get('角色名'))}】"]
        for save in slot.get("saves") or []:
            label = save.get("label") or slot.get("进度") or "无"
            b.append(f"- File_{_s(save.get('序号'))} {_fmt_ts(save.get('时间戳'))} — {_s(label)}")
    if not shown:
        b += ["", "尚无存档可续"]
    b += _title_hint(resp)
    b += ["", "请输入指令（选择存档、返回标题）："]
    return "\n".join(b)


def _draft(resp):
    return resp.get("创建草稿") if isinstance(resp.get("创建草稿"), dict) else {}


def _render_title_name(resp):
    draft = _draft(resp)
    b = ["### 【人物创建】", "", "—— 第一步 · 立名 ——", "",
         "请告知姓名、性别与年龄（如：沈听雪，女，18岁）。"]
    if draft.get("名称"):
        b += ["", f"当前：{_s(draft.get('名称'))}（{_s(draft.get('性别'))}）{_s(draft.get('年龄'))}岁"]
    b += _title_hint(resp)
    b += ["", "请输入指令（姓名、性别、年龄、返回标题）："]
    return "\n".join(b)


def _render_title_stats(resp):
    draft = _draft(resp)
    left = resp.get("剩余点数") or {}
    primary = draft.get("一级属性") or {}
    martial = draft.get("武艺") or {}
    technique = draft.get("技艺") or {}
    polar = draft.get("极性") or {}
    b = ["### 【人物创建】　第二步 · 分配资质", "",
         f"{_s(draft.get('名称'))}（{_s(draft.get('性别'))}）{_s(draft.get('年龄'))}岁", "",
         f"基础属性　剩余{_s(left.get('一级属性'), 24)}点　单项≤12",
         f"  内功 —— {_s(primary.get('内功'))}　力道 —— {_s(primary.get('力道'))}",
         f"  身法 —— {_s(primary.get('身法'))}　根骨 —— {_s(primary.get('根骨'))}", "",
         f"武艺点数　剩余{_s(left.get('武艺'), 36)}点　单项≤12",
         f"  搏击 —— {_s(martial.get('搏击'))}　剑法 —— {_s(martial.get('剑法'))}　刀法 —— {_s(martial.get('刀法'))}",
         f"  长兵 —— {_s(martial.get('长兵'))}　奇门 —— {_s(martial.get('奇门'))}　暗器 —— {_s(martial.get('暗器'))}", "",
         f"技艺点数　剩余{_s(left.get('技艺'), 36)}点　单项≤12",
         f"  音律 —— {_s(technique.get('音律'))}　弈棋 —— {_s(technique.get('弈棋'))}　诗书 —— {_s(technique.get('诗书'))}",
         f"  绘画 —— {_s(technique.get('绘画'))}　医术 —— {_s(technique.get('医术'))}　博物 —— {_s(technique.get('博物'))}", "",
         "极性　各择其一",
         f"  阴阳 —— {_s(polar.get('内功'))}（阴、阳、中）",
         f"  刚柔 —— {_s(polar.get('力道'))}（刚、柔、中）",
         f"  动静 —— {_s(polar.get('身法'))}（动、静、中）",
         f"  巧拙 —— {_s(polar.get('根骨'))}（巧、拙、中）"]
    help_lines = resp.get("属性说明") or []
    if help_lines:
        b += ["", "属性含义"] + [f"- {_s(line)}" for line in help_lines]
    b += _title_hint(resp)
    b += ["", "请输入指令（属性加点、随机分配、确认加点、属性含义、返回标题）："]
    return "\n".join(b)


def _render_title_skills(resp):
    draft = _draft(resp)
    b = ["### 【人物创建】　第三步 · 选择初始武学", "",
         f"{_s(draft.get('名称'))}（{_s(draft.get('性别'))}）{_s(draft.get('年龄'))}岁", "",
         "可择一门入门武学，并配发对应兵器："]
    for skill in resp.get("初始武学列表") or []:
        b.append(f"- {_s(skill.get('类型'))}：{_s(skill.get('门派'))}《{_s(skill.get('名称'))}》，配【{_s(skill.get('武器'))}】")
    b += _title_hint(resp)
    b += ["", "请输入指令（选择武学、武学详情、返回上一步、返回标题）："]
    return "\n".join(b)


def _gain_parts(effect, prefix=""):
    parts = []
    if not isinstance(effect, dict):
        return parts
    for key, value in effect.items():
        label = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict):
            parts.extend(_gain_parts(value, label))
        elif isinstance(value, bool):
            if value:
                parts.append(label)
        elif isinstance(value, (int, float)):
            if "倍率" in key:
                parts.append(f"{label}{float(value):+g}" if abs(value) >= 1 else f"{label}{float(value) * 100:+g}%")
            else:
                parts.append(f"{label}{value:+g}")
        elif value not in (None, ""):
            parts.append(f"{label}{_s(value)}")
    return parts


def _render_title_skill_detail(resp):
    skill = resp.get("武学详情") or {}
    if not skill:
        return _render_title_skills(resp)
    b = [f"### 《{_s(skill.get('名称'))}》{_s(skill.get('门派'))} · {_s(skill.get('类型'))}", "",
         _txt(skill.get("描述")), ""]
    moves = skill.get("招式") or []
    if moves:
        b.append(f"招式：{_names(moves)}")
    cooldown = skill.get("冷却时间", 0) or 0
    b += [f"类型：{_s(skill.get('类型'))}　品级：{_s(skill.get('品名'))}",
          f"威力倍率：{_s(skill.get('威力倍率'))}　内力消耗：{_s(skill.get('内力消耗'))}　冷却：{'无' if not cooldown else _s(cooldown) + ' tick'}",
          f"目标范围：{_s(skill.get('目标范围'))}", "", "十境增益", "", "| 等级 | 增益 |", "|------|------|"]
    gains = {entry.get("等级"): entry.get("效果") for entry in skill.get("等级增益") or [] if isinstance(entry, dict)}
    for level in range(1, 11):
        parts = _gain_parts(gains.get(level) or {})
        b.append(f"| Lv{level} | {'、'.join(parts) if parts else '—'} |")
    b += ["", f"特效：{_s(skill.get('特效')).strip() or '无'}"]
    b += _title_hint(resp)
    b += ["", "请输入指令（选择武学、查看其他武学、返回武学选择、返回标题）："]
    return "\n".join(b)


def _render_title(resp):
    state = _s(resp.get("标题状态"), "主页")
    if state == "读档":
        return _render_title_saves(resp)
    if state == "创建-立名":
        return _render_title_name(resp)
    if state == "创建-资质":
        return _render_title_stats(resp)
    if state == "创建-武学":
        return _render_title_skills(resp)
    if state == "创建-武学详情":
        return _render_title_skill_detail(resp)
    return _render_title_home(resp)


def _render_save(resp):
    slots = resp.get("存档列表") or []
    entry = slots[0] if isinstance(slots, list) and slots and isinstance(slots[0], dict) else {}
    slot_no = entry.get("slot", resp.get("槽位"))
    name = _s(entry.get("角色名"))
    head = f"【读档 · Slot_{_s(slot_no)}{' ' + name if name else ''}】"
    b = [head, ""]
    saves = entry.get("saves") or []
    if not saves:
        b.append("当前角色尚无可读取存档")
    else:
        for s in saves:
            label = s.get("label") or entry.get("进度") or "无"
            b.append(f"- File_{_s(s.get('序号'))} {_fmt_ts(s.get('时间戳'))} — {_s(label)}")
    b += ["", "请输入指令（选择存档、返回游历）："]
    return "\n".join(b)


def _wuxue_row(w):
    """携带/可用主动武学行（含全角空格开头的特效行）。"""
    line = (f"- `{_s(w.get('名称'))}` Lv{_s(w.get('等级'))}"
            f"（{_s(w.get('类型'))} / {_s(w.get('目标范围'))} / 威力{_s(w.get('威力倍率'))}"
            f" / 内力{_s(w.get('内力消耗'))} / 冷却{_cooldown(w)}）")
    eff = _s(w.get("特效")).strip() or "无"
    return line + f"\n　特效：{eff}"


def _render_wuxue(resp):
    b = [f"### 【更换武学 · {_s(resp.get('角色'))}】"]
    changes = _settle_lines(resp)
    if changes:
        b += ["", "\n".join(changes)]
    b += ["", "运转心法"]
    xinfa = _s(resp.get("运转心法")).strip() or "无"
    b.append(f"- `{xinfa}`")
    b.append(f"　特效：{_s(resp.get('运转心法特效')).strip() or '无'}")
    carried = resp.get("携带武学") or []
    b += ["", f"携带武学（{len(carried)}/4）"]
    if carried:
        for w in carried:
            b.append(_wuxue_row(w))
    else:
        b.append("- （无）")
    avail = resp.get("可用武学") or []
    b += ["", "可用主动武学（已习得、未携带）"]
    if avail:
        for w in avail:
            b.append(_wuxue_row(w))
    else:
        b.append("- （无）")
    b += ["", "请输入指令（运转心法、装上武学、卸下武学、替换武学、返回游历、"
              "可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_equip(resp):
    b = [f"### 【更换装备 · {_s(resp.get('角色'))}】"]
    changes = _settle_lines(resp)
    if changes:
        b += ["", "\n".join(changes)]
    cur = resp.get("当前装备") or {}

    def slot_line(label, key, with_subtype=False):
        nm = cur.get(key)
        if not nm:
            return f"- {label}：空"
        if with_subtype:
            rec = dq.get("物品", nm) or {}
            sub = rec.get("子类型")
            return f"- {label}：{nm}（{sub}）" if sub else f"- {label}：{nm}"
        return f"- {label}：{nm}"

    b += ["", "当前装备",
          slot_line("武器1", "武器1", with_subtype=True),
          slot_line("武器2", "武器2", with_subtype=True),
          slot_line("护甲", "护甲"),
          slot_line("饰品", "饰品"),
          slot_line("冠巾", "冠巾")]
    avail = resp.get("可换装备") or []
    b += ["", "可换装备"]
    if avail:
        for e in avail:
            sub = e.get("子类型") or e.get("类型") or "—"
            b.append(f"- `{_s(e.get('名称'))}`（{sub}/{_grade(e)}）")
    else:
        b.append("- （无）")
    b += ["", "请输入指令（装备 [物品] [槽位]、卸下 [槽位]、返回游历、"
              "可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_item(resp):
    b = [f"### 【更换道具 · {_s(resp.get('角色'))}】"]
    changes = _settle_lines(resp)
    if changes:
        b += ["", "\n".join(changes)]
    carried = resp.get("携带道具") or []
    b += ["", f"携带道具（{len(carried)}/4）"]
    for e in carried:
        b.append(f"- `{_s(e.get('名称'))}`（{_s(e.get('子类型'))}）×{_s(e.get('数量'))}"
                 + "\n" + _effect_row(e))
    if not carried:
        b.append("- （无）")
    avail = resp.get("可换道具") or []
    b += ["", "可换道具"]
    if avail:
        for e in avail:
            b.append(f"- `{_s(e.get('名称'))}`（{_s(e.get('子类型'))}）×{_s(e.get('数量'))}"
                     + "\n" + _effect_row(e))
    else:
        b.append("- （无）")
    b += ["", "请输入指令（携带 [物品]、卸下 [物品]、替换 [新物品] [原物品]、返回游历、"
              "可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_mastery(resp):
    b = [f"### 【武学精进 · {_s(resp.get('角色'))}】"]
    changes = _settle_lines(resp)
    if changes:
        b += ["", "\n".join(changes)]
    table = _s(resp.get("十境表")).strip()
    b += ["", table or "（未习得任何武学）", "",
          "请输入指令（精进下一境界、更换武学 [武学]、返回游历、"
          "可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_character(resp):
    d = resp.get("角色信息") or {}
    b = [f"### 【人物 · {_s(d.get('名称'))}】 {_s(d.get('性别'))} {_s(d.get('年龄'))}岁"
         f"　经验：{_s(d.get('经验值'))}"]
    attr = d.get("一级属性") or {}
    pol = d.get("极性") or {}

    def head(k, pk):
        return f"{k}/{pol[pk]}" if pol.get(pk) else k

    b += ["",
          f"| {head('内功', '阴阳')} | {head('力道', '刚柔')} | {head('身法', '动静')} | {head('根骨', '巧拙')} |",
          "|------|------|------|------|",
          f"| {_s(attr.get('内功'))} | {_s(attr.get('力道'))} | {_s(attr.get('身法'))} | {_s(attr.get('根骨'))} |",
          "",
          "| 搏击 | 剑法 | 刀法 | 长兵 | 奇门 | 暗器 |",
          "|------|------|------|------|------|------|"]
    wy = d.get("武艺") or {}
    b.append("| " + " | ".join(_s(wy.get(k)) for k in ("搏击", "剑法", "刀法", "长兵", "奇门", "暗器")) + " |")
    b += ["",
          "| 音律 | 弈棋 | 诗书 | 绘画 | 医术 | 博物 |",
          "|------|------|------|------|------|------|"]
    jy = d.get("技艺") or {}
    b.append("| " + " | ".join(_s(jy.get(k)) for k in ("音律", "弈棋", "诗书", "绘画", "医术", "博物")) + " |")
    sec = d.get("二级属性") or {}
    b += ["",
          "| 气血 | 内力 | 攻击力 | 防御力 | 速度 | 精准 | 识破 | 暴击 |",
          "|------|------|--------|--------|------|------|------|------|",
          f"| {_s(d.get('气血'))}/{_s(d.get('气血上限'))} | {_s(d.get('内力'))}/{_s(d.get('内力上限'))} | "
          f"{_s(sec.get('攻击力'))} | {_s(sec.get('防御力'))} | {_s(sec.get('速度'))} | "
          f"{_s(sec.get('精准'))} | {_s(sec.get('识破'))} | {_s(sec.get('暴击'))} |"]
    xinfa = _s(d.get("运转心法")).strip() or "无"
    skills = _names(d.get("携带技能")) or "无"
    b += ["", f"运转心法：{xinfa}", f"携带武学：{skills}"]
    equip = d.get("装备") or {}

    def eq(k):
        return _s(equip.get(k)).strip() or "空"

    b += ["", "装备",
          f"武器1：{eq('武器1')}　武器2：{eq('武器2')}",
          f"护甲：{eq('护甲')}　饰品：{eq('饰品')}　冠巾：{eq('冠巾')}",
          f"携带物品：{_names(d.get('携带物品')) or '无'}{'（已殁）' if d.get('死亡') else ''}",
          "",
          "请输入指令（查看其他角色 [名称]、返回游历、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_bag(resp):
    f = resp.get("筛选") or {}
    parts = []
    for label, key in (("类型", "类型"), ("子类型", "子类型"), ("适用场合", "适用场合")):
        if f.get(key):
            parts.append(f"{label} = {_join_vals(f[key])}")
    filter_txt = "　".join(parts) if parts else "全部"
    b = [f"### 【背包 · {_s(resp.get('角色'))}】", f"筛选：{filter_txt}", ""]
    items = resp.get("物品列表") or []
    if items:
        b += ["| 物品 | 数量 | 类型 | 子类型 | 品级 | 适用场合 |",
              "|------|------|------|--------|------|----------|"]
        for e in items:
            b.append(f"| `{_s(e.get('名称'))}` | ×{_s(e.get('数量'))} | {_s(e.get('类型'))} | "
                     f"{_sub_or_dash(e)} | {_grade(e)} | {_s(e.get('适用场合')) or '—'} |")
    else:
        b.append("物品栏空空如也")
    b += ["", "请输入指令（使用 [物品]、筛选 [类型/子类型/适用场合]、返回游历、"
              "可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_travel(resp):
    b = [f"### 【驿站 · {_s(resp.get('当前区域'))}】{_s(resp.get('驿站类型'))}", ""]
    routes = resp.get("路线") or []
    if routes:
        b.append("可往：")
        for r in routes:
            b.append(f"- `{_s(r.get('目的地'))}`　{_s(r.get('耗时'))}天　{_money(r.get('费用'))}")
    else:
        b.append("此驿站暂无直达路线，需经他处换乘")
    b += ["", "请输入指令（前往 [目的地]、返回游历、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_inn(resp):
    b = [f"### 【客栈 · {_s(resp.get('场景'))}】　金钱 {_money(resp.get('金钱'))}",
         "", "固定休息4时辰（32刻）", ""]
    tiers = resp.get("等级") or []
    if tiers:
        b += ["| 等级 | 每刻单价 | 总费用 | 体力/时辰 | 气血内力/时辰 |",
              "|------|------|------|------|------|"]
        for t in tiers:
            unit = int(t.get("每刻单价", 0) or 0)
            b.append(f"| `{_s(t.get('等级'))}` | {_money(unit)} | {_money(unit * 32)} | "
                     f"{_s(t.get('体力每时辰'))} | 上限{_pct(t.get('气血内力比例'))} |")
    b += ["", "请输入指令（休息 [等级]、返回游历、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_wuxue_list(resp):
    b = [f"### 【武学 · {_s(resp.get('角色'))}】", "", "主动武学"]
    active = resp.get("主动武学") or []
    if active:
        for w in active:
            line = (f"- `{_s(w.get('名称'))}` Lv{_s(w.get('等级'))}"
                    f"（{_s(w.get('类型'))} / {_grade(w)} / 威力{_s(w.get('威力倍率'))}"
                    f" / 内力{_s(w.get('内力消耗'))} / 冷却{_cooldown(w)}）")
            b.append(line + f"\n　特效：{_s(w.get('特效')).strip() or '无'}")
    else:
        b.append("（无）")
    b += ["", "心法"]
    xinfa = resp.get("心法") or []
    if xinfa:
        for w in xinfa:
            line = f"- `{_s(w.get('名称'))}` Lv{_s(w.get('等级'))}（{_grade(w)}）"
            b.append(line + f"\n　特效：{_s(w.get('特效')).strip() or '无'}")
    else:
        b.append("（无）")
    b += ["", "请输入指令（查看其他角色 [名称]、查看武学详情 [武学]、返回游历、"
              "可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _trade_table(rows):
    out = ["| 物品 | 数量 | 单价 | 类型 | 子类型 | 品级 |",
           "|------|------|------|------|--------|------|"]
    for e in rows:
        out.append(f"| `{_s(e.get('名称'))}` | ×{_s(e.get('数量'))} | {_money(e.get('价格'))} | "
                   f"{_s(e.get('类型'))} | {_sub_or_dash(e)} | {_grade(e)} |")
    return out


def _merchant_tag(resp):
    return "（商人）" if resp.get("商人") else ""


def _render_trade_buy(resp):
    seller = _s(resp.get("卖家"))
    b = [f"### 【购买 · {seller}】{_merchant_tag(resp)}　金钱 {_money(resp.get('金钱'))}", ""]
    offer = resp.get("货架") or []
    if offer:
        b += _trade_table(offer)
    else:
        b.append(f"{seller}暂无可售物品")
    b += ["", "请输入指令（购买 [物品] [数量]、返回游历、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_trade_sell(resp):
    buyer = _s(resp.get("买家"))
    b = [f"### 【出售 · 收购方 {buyer}】{_merchant_tag(resp)}　金钱 {_money(resp.get('金钱'))}", ""]
    items = resp.get("可售物品") or []
    if items:
        b += _trade_table(items)
    else:
        b.append("物品栏空空如也")
    b += ["", "请输入指令（出售 [物品] [数量]、返回游历、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_message(resp):
    hint = _s(resp.get("提示")).strip() or "指令不合法或信息不足，请重新输入。"
    return f"✗ {hint}\n\n请重新输入指令："


def _render_map(resp):
    b = [f"### 【{_s(resp.get('当前区域'))} · 场景地图】 当前：{_s(resp.get('当前场景'))}",
         "", "```text", _s(resp.get("邻接图")), "```"]
    station = _s(resp.get("驿站出口")).strip()
    if station:
        b += ["", f"（出城：`{station}`，{_s(resp.get('驿站类型'))}）"]
    known = resp.get("已知地点") or []
    marks = []
    for p in known:
        nm = _s(p.get("名称"))
        tag = "（当前）" if "当前" in (p.get("标记") or []) else (
            "（出城）" if station and nm == station else "")
        marks.append(f"`{nm}`{tag}")
    b += ["", f"已知地点：{'、'.join(marks) if marks else '（无）'}", "",
          "请输入指令（前往地点、返回游历、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


def _render_battle(resp):
    """拼接 battle.py 已生成的规范战报与玩家行动面板。"""
    sections = []
    report = _txt(resp.get("战报"))
    player_ui = _txt(resp.get("玩家界面"))
    if report:
        sections.append(report)
    if player_ui:
        sections.append(player_ui)
    return "\n\n".join(sections)


def _render_battle_end(resp):
    """在规范终局战报后追加确定性的逐人处决面板。"""
    descriptions = {
        "败阵": "倒地受制，气息尚存",
        "存活": "弃械受制，气息尚存",
        "认输": "俯首受制，气息尚存",
    }
    panel = ["### 【处决裁定】"]
    candidates = resp.get("处决候选") or []
    if candidates:
        panel += ["", "胜方处置败方，逐人决定："]
        for candidate in candidates:
            name = _s(candidate.get("名称")) if isinstance(candidate, dict) else _s(candidate)
            state = _s(candidate.get("状态")) if isinstance(candidate, dict) else ""
            description = descriptions.get(state, "已被制住，气息尚存")
            panel.append(f"- {name}（{description}）")
        panel += ["", "请逐人答复（杀 / 放，可补充处置细节）："]
    else:
        panel += ["", "敌方均已逃走，无可处决之人。", "", "请输入指令（结束战斗）："]

    report = _txt(resp.get("战报"))
    sections = [report] if report else []
    sections.append("\n".join(panel))
    return "\n\n".join(sections)


def _render_clue(resp):
    b = ["### 【线索栏】"]
    ongoing = resp.get("进行中") or []
    closed = resp.get("已关闭") or []
    if not ongoing and not closed:
        b += ["", "尚无线索"]
    for label, group in (("—— 进行中 ——", ongoing), ("—— 已关闭 ——", closed)):
        if not group:
            continue
        b += ["", label]
        for c in group:
            line = f"`{_s(c.get('名称'))}`"
            if label.endswith("已关闭 ——"):
                line += "　已了结"
            b.append(line)
            for i, node in enumerate(c.get("进展节点") or [], start=1):
                desc = _s(node.get("描述"))
                reward = _s(node.get("奖励")).strip()
                if reward:
                    desc += f"（{reward}）"
                b.append(f"{i}. {desc}")
    b += ["", "请输入指令（返回游历、可通过`指令查询`了解全部指令）："]
    return "\n".join(b)


RENDERERS = {
    "title-ui": _render_title,
    "exploration-ui": _render_exploration,
    "save-ui": _render_save,
    "exploration-battle-ui": _render_exploration_battle,
    "battle-ui": _render_battle,
    "battle-end-ui": _render_battle_end,
    "wuxue-ui": _render_wuxue,
    "equip-ui": _render_equip,
    "item-ui": _render_item,
    "mastery-ui": _render_mastery,
    "character-ui": _render_character,
    "bag-ui": _render_bag,
    "travel-ui": _render_travel,
    "inn-ui": _render_inn,
    "wuxue-list-ui": _render_wuxue_list,
    "trade-buy-ui": _render_trade_buy,
    "trade-sell-ui": _render_trade_sell,
    "message-ui": _render_message,
    "map-ui": _render_map,
    "clue-ui": _render_clue,
}


# ----------------------------- 统一挂载入口 -----------------------------

def attach_render_text(response):
    """在最终 response 上挂载 渲染文本（原位并返回）。

    - 非目标 UI：原样返回，不加字段；
    - dsh：目标 UI 固定 渲染文本=""，不执行模板拼接；
    - 其余模式：按模板生成完整 Markdown；
    - exploration-ui 带 错误（judge 自检失败）：GM 修正重试路径，不生成玩家界面文本。
    """
    ui = response.get("界面")
    if ui not in MARKDOWN_UI_IDS:
        return response
    response["渲染模式"] = render_mode()
    if is_dsh_mode():
        response["渲染文本"] = ""
        return response
    if ui == "exploration-ui" and response.get("错误"):
        return response
    response["渲染文本"] = RENDERERS[ui](response)
    return response
