#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine ui 层(由 engine.py 拆分)。"""
import os, sys
from common import dao as dq
from common.render_mode import is_dsh_mode, render_mode
from world import mastery as ms
from store import save_manager as sm
from world import trade as td
from world import scene as sc
from store import explore_store as es

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from settle.engine_io import _build_state, _load_map, _read_char, _resolve_region, _set_slot, _station_type, _write_char
from settle.markdown_ui import attach_render_text

# 驿站路线单价（铜钱/天），按驿站类型：海驿最贵（海船）、边驿次之（偏远险路）、陆驿车马、山驿山路、水驿船票最廉
_STATION_PRICE = {"水驿": 100, "陆驿": 150, "山驿": 120, "海驿": 200, "边驿": 180}

# 休息四等级：每时辰(8刻)恢复体力、气血内力按上限比例、每刻单价(钱)
# 差=野外露宿(免费/不回气血内力)；中/上/奢=客栈民宿(收费/按比例回气血内力)
_REST_TIERS = {
    "露宿": {"体力": 10, "气血比例": 0.0, "每刻单价": 0},
    "简朴": {"体力": 15, "气血比例": 0.15, "每刻单价": 4},
    "中等": {"体力": 20, "气血比例": 0.20, "每刻单价": 5},
    "奢华": {"体力": 25, "气血比例": 0.25, "每刻单价": 6},
}

# inn-ui 展示的等级（露宿不经 inn-ui）
_INN_TIERS = ["简朴", "中等", "奢华"]

# 商人货架缓存：存于 slot 根目录 merchant.json
#（扁平 key：{"区域-地点-卖家名": {"上架时间": N, "库存": {物品名: 剩余数量}}}），同名商人在不同地点各记一摊；
# 上架时间取游戏内当前时间（explore.当前时间，刻）；当前时间与上架时间对 960 取余不相等即换货
#（每 960 刻一个换货周期，96 刻/天 → 每 10 天换一次）。
# 缓存只记物品名与剩余数量，详细字段（类型/子类型/品级/价格/描述）取数时由 explore 从物品库
# 实时补全，保证与物品库定义同步。merchant.json 随存档保存/读档恢复（见 save_manager 的 merchant_cache 字段）。
_MERCHANT_PERIOD = 960

_ITEM_DETAIL_FIELDS = ("类型", "子类型", "品级", "价格", "描述")

# 品级数字 → 品名（品级0~3）；超出范围回退为数字字符串
_GRADE_NAMES = {0: "凡品", 1: "上品", 2: "珍品", 3: "绝品"}

def _wuxue_list(char, skills_db, carried_only=False):
    """组装武学列表项：[{名称, 等级, 类型, 目标范围, 威力倍率, 内力消耗, 冷却时间, 特效}]。
    carried_only=True 仅携带技能，否则全部已习得主动武学（排除心法）。取武学基准值。
    特效为按等级生成的一句话描述，无特效时为空串。"""
    learned = dq.get_learned_skills_with_level(char)
    carried = set(char.get("携带技能") or [])
    out = []
    for name, level in learned:
        s = skills_db.get(name)
        if not s or s.get("类型") == "心法":
            continue
        if carried_only and name not in carried:
            continue
        out.append({
            "名称": name, "等级": level, "类型": s.get("类型"),
            "品级": s.get("品级"), "品名": _grade_name(s.get("品级")),
            "目标范围": s.get("目标范围") or "敌方单体",
            "威力倍率": s.get("威力倍率"), "内力消耗": s.get("内力消耗"),
            "冷却时间": s.get("冷却时间", 0) or 0,
            "特效": dq.describe_wuxue(name, level),
        })
    return out

def _build_wuxue(slot, role):
    """配置武学界面数据：角色名/运转心法(+特效)/携带武学/可用主动武学。"""
    char = _read_char(slot, role)
    if not char:
        return {"界面": "exploration-ui", "错误": f"未找到角色【{role}】"}
    skills_db = dq.load_all("武学")
    carried = _wuxue_list(char, skills_db, carried_only=True)
    available = [w for w in _wuxue_list(char, skills_db, carried_only=False)
                 if w["名称"] not in (char.get("携带技能") or [])]
    # 运转心法特效：按角色该心法等级生成一句话，无特效为空串
    xinfa = char.get("运转心法")
    xinfa_effect = ""
    if xinfa:
        level = dict(dq.get_learned_skills_with_level(char)).get(xinfa, 1)
        xinfa_effect = dq.describe_wuxue(xinfa, level)
    return {
        "界面": "wuxue-ui", "角色": role,
        "运转心法": xinfa, "运转心法特效": xinfa_effect,
        "携带武学": carried, "可用武学": available,
    }

def _wuxue_list_entry(name, level):
    """组装单个已习得武学列表项：{名称, 等级, 类型, 品级, 目标范围, 威力倍率, 内力消耗, 冷却时间, 特效, 描述}。
    心法无 威力倍率/内力消耗/冷却时间/目标范围 等字段则缺省。特效按等级一句话，无则空串。"""
    s = dq.get("武学", name) or {}
    entry = {
        "名称": name, "等级": level, "类型": s.get("类型"),
        "品级": s.get("品级"), "品名": _grade_name(s.get("品级")),
        "描述": s.get("描述"),
    }
    for k in ("目标范围", "威力倍率", "内力消耗", "冷却时间"):
        if k in s:
            entry[k] = s[k]
    entry["特效"] = dq.describe_wuxue(name, level)
    return entry

def _build_wuxue_list(slot, role):
    """武学列表界面数据：角色已习得的全部武学，主动武学与心法分两个数组返回。"""
    char = _read_char(slot, role)
    if not char:
        return {"界面": "exploration-ui", "错误": f"未找到角色【{role}】"}
    learned = dq.get_learned_skills_with_level(char)
    active, xinfa = [], []
    for name, level in learned:
        s = dq.get("武学", name) or {}
        entry = _wuxue_list_entry(name, level)
        (xinfa if s.get("类型") == "心法" else active).append(entry)
    return {"界面": "wuxue-list-ui", "角色": role, "主动武学": active, "心法": xinfa}

def _build_equip(slot, role):
    """配置装备界面数据：角色名/当前装备(5槽)/可换装备(物品栏装备类)。"""
    char = _read_char(slot, role)
    if not char:
        return {"界面": "exploration-ui", "错误": f"未找到角色【{role}】"}
    equip = char.get("装备", {}) or {}
    current = {s: equip.get(s) for s in ("武器1", "武器2", "护甲", "饰品", "冠巾")}
    # 可换装备：物品栏中属装备类、且未穿在槽位的
    slots_eq = set(equip.values())
    bag = char.get("物品") or []
    avail_names, seen = [], set()
    for it in bag:
        nm = it if isinstance(it, str) else (it.get("名称") if isinstance(it, dict) else None)
        if nm and nm not in seen and dq.is_equipment(nm) and nm not in slots_eq:
            seen.add(nm)
            rec = dq.get("物品", nm)
            grade = rec.get("品级") if rec else None
            avail_names.append({"名称": nm, "类型": rec.get("类型") if rec else None,
                                "子类型": rec.get("子类型") if rec else None,
                                "品级": grade, "品名": _grade_name(grade)})
    return {
        "界面": "equip-ui", "角色": role,
        "当前装备": current, "可换装备": avail_names,
    }

def _build_item(slot, role):
    """配置物品（携带道具）界面数据：角色名/携带道具/可换道具（dao.item_panel）。"""
    panel = dq.item_panel(role)
    if panel is None:
        return {"界面": "exploration-ui", "错误": f"未找到角色【{role}】"}
    return {
        "界面": "item-ui", "角色": role,
        "携带道具": panel.get("携带道具", []),
        "可换道具": panel.get("可换道具", []),
    }

def _build_mastery(slot, role, skill_name):
    """武学精进界面数据：角色名/武学名/十境表文本/经验/等级。
    skill_name 缺省取角色第一门武学。"""
    char = _read_char(slot, role)
    if not char:
        return {"界面": "exploration-ui", "错误": f"未找到角色【{role}】"}
    if not skill_name:
        learned = dq.get_learned_skills_with_level(char)
        skill_name = learned[0][0] if learned else None
    if not skill_name:
        return {"界面": "mastery-ui", "角色": role, "武学": None, "十境表": "（未习得任何武学）",
                "经验值": char.get("经验值", 0), "等级": 0}
    level = ms.get_learned_level(char, skill_name) or 0
    exp = char.get("经验值", 0) or 0
    # dsh：只出结构化十境表数据（卡片消费，渲染文本为空）；
    # LLM：只出十境表文本（供 Markdown 直拼）；其余（WEB_UI 等）：两者并存。
    if is_dsh_mode():
        table, _ = ms.build_table_struct(char, skill_name, exp, level)
        return {
            "界面": "mastery-ui", "角色": role, "武学": skill_name,
            "经验值": exp, "等级": level, "十境表数据": table,
        }
    lines, _ = ms.build_table(char, skill_name, exp, level)
    data = {
        "界面": "mastery-ui", "角色": role, "武学": skill_name,
        "十境表": "\n".join(lines) if lines else "", "经验值": exp, "等级": level,
    }
    if render_mode() != "LLM":
        table, _ = ms.build_table_struct(char, skill_name, exp, level)
        data["十境表数据"] = table
    return data

def _character_detail(slot, role):
    """取单个角色的信息视图（供 character-ui）。
    属性为武学反哺+装备加成后的派生值（dao.derive_character 同源）。
    含：基础(名称/性别/年龄/经验值/气血内力及上限)、一级属性、极性、武艺、技艺、二级属性、
        携带技能、运转心法、装备(5槽)、携带物品、死亡。不返回阵营/关系度/完整武学栏/完整物品栏。"""
    char = _read_char(slot, role)
    if not char:
        return None
    try:
        derived = dq.derive_character(char, dq.load_characters(), dq.load_skills())
    except (KeyError, TypeError):
        derived = char
    equip = char.get("装备", {}) or {}
    return {
        "名称": char.get("名称"), "性别": char.get("性别"), "年龄": char.get("年龄"),
        "经验值": char.get("经验值", 0),
        "气血": derived.get("气血"), "气血上限": derived.get("气血上限"),
        "内力": derived.get("内力"), "内力上限": derived.get("内力上限"),
        "一级属性": char.get("一级属性", {}), "极性": char.get("极性", {}),
        "武艺": derived.get("武艺", char.get("武艺", {})), "技艺": char.get("技艺", {}),
        "二级属性": derived.get("二级属性", {}),
        "携带技能": char.get("携带技能") or [],
        "运转心法": char.get("运转心法"),
        "装备": {s: equip.get(s) for s in ("武器1", "武器2", "护甲", "饰品", "冠巾")},
        "携带物品": char.get("携带物品") or [],
        "死亡": bool(char.get("死亡", False)),
    }

def _build_character(slot, role):
    """角色信息界面数据：指定角色的完整信息（属性派生含武学+装备反哺）。"""
    detail = _character_detail(slot, role)
    if detail is None:
        return {"界面": "exploration-ui", "错误": f"未找到角色【{role}】"}
    return {"界面": "character-ui", "角色": role, "角色信息": detail}

def _build_travel(slot):
    """驿站界面数据：当前区域的驿站类型 + 可达直达路线（目的地/耗时/费用）。
    费用 = 耗时(天) × 该驿站类型单价。当前区域由 explore.当前位置 解析。"""
    m = _load_map()
    nodes = m.get("节点", {})
    adj = m.get("邻接", {})
    cur = es.get(slot, "当前位置") or ""
    region = _resolve_region(cur, nodes)
    if region is None:
        return {"界面": "exploration-ui", "错误": f"当前位置【{cur}】无对应驿站"}
    stype = nodes.get(region, "陆驿")
    price = _STATION_PRICE.get(stype, 150)
    routes = []
    for dest, days in adj.get(region, {}).items():
        routes.append({"目的地": dest, "耗时": int(days), "费用": int(days) * price})
    return {"界面": "travel-ui", "当前区域": region, "驿站类型": stype,
            "路线": routes}

def _build_bag(slot, role, action=None):
    """背包界面数据：主控物品栏按筛选条件列出物品（按种类合并计数）。
    筛选参数（均可选）：筛选类型（武器/护甲/消耗品/…）、筛选子类型（剑/刀/丹药/…）、
    适用场合（世界/战斗/通用，传"世界"则仅列大世界可用物品）。
    每项含 名称/数量/类型/子类型/品级/适用场合/使用效果（无则缺省）。"""
    action = action or {}
    char = _read_char(slot, role)
    if not char:
        return {"界面": "exploration-ui", "错误": f"未找到角色【{role}】"}
    ftype = action.get("筛选类型")
    fsub = action.get("筛选子类型")
    fscene = action.get("适用场合")
    # 类型/子类型支持单值或数组（命中任一）；适用场合为单值
    ftype_set = {ftype} if isinstance(ftype, str) else (set(ftype) if isinstance(ftype, list) else set())
    fsub_set = {fsub} if isinstance(fsub, str) else (set(fsub) if isinstance(fsub, list) else set())
    bag = char.get("物品") or []
    counts, order = {}, []
    for it in bag:
        nm = it if isinstance(it, str) else (it.get("名称") if isinstance(it, dict) else None)
        if not nm:
            continue
        if nm not in counts:
            order.append(nm)
            counts[nm] = 0
        counts[nm] += 1
    items = []
    for nm in order:
        rec = dq.get("物品", nm) or {}
        if ftype_set and rec.get("类型") not in ftype_set:
            continue
        if fsub_set and rec.get("子类型") not in fsub_set:
            continue
        if fscene and not dq.usable_in(rec, fscene):
            continue
        entry = {"名称": nm, "数量": counts[nm], "类型": rec.get("类型"),
                  "子类型": rec.get("子类型"),
                  "品级": rec.get("品级"), "品名": _grade_name(rec.get("品级")),
                  "适用场合": rec.get("适用场合")}
        if "使用效果" in rec:
            entry["使用效果"] = rec["使用效果"]
        items.append(entry)
    return {"界面": "bag-ui", "角色": role,
            "筛选": {"类型": ftype, "子类型": fsub, "适用场合": fscene},
            "物品列表": items}

def _norm_elements(els):
    """场景要素归一化为 [{主体, 描写, 特殊指令?}, ...] 对象数组。
    兼容两种输入：{"主体":..,"描写":..,"特殊指令":..} 对象，或旧版 "主体（描写）" 字符串（按首个「（」拆分）。
    描写可缺省（空字符串）；特殊指令为对象数组 [{名称, 可用}, ...]，可用为 bool（GM 据场景判断，
    如玩家被困时将远行（舟车）置 false）。非数组/元素无主体 → 返回 None；特殊指令非法 → None。"""
    if not isinstance(els, list):
        return None
    out = []
    for e in els:
        cmds = None
        if isinstance(e, dict):
            sub = str(e.get("主体", "")).strip()
            if not sub:
                return None
            desc = str(e.get("描写", "") or "").strip()
            cmds = e.get("特殊指令")
        elif isinstance(e, str):
            s = e.strip()
            if not s:
                continue
            if "（" in s:
                sub, desc = s.split("（", 1)
                sub = sub.strip()
                desc = desc.rstrip("）").strip()
            else:
                sub, desc = s, ""
            if not sub:
                return None
        else:
            return None
        # 特殊指令归一化为 [{名称, 可用}, ...]；每项须为对象、名称非空、可用为 bool。非法 → None
        if cmds is not None:
            if not isinstance(cmds, list):
                return None
            norm_cmds = []
            for c in cmds:
                if not isinstance(c, dict):
                    return None
                name = str(c.get("名称", "")).strip()
                if not name:
                    return None
                if not isinstance(c.get("可用"), bool):
                    return None
                norm_cmds.append({"名称": name, "可用": c["可用"]})
            cmds = norm_cmds or None
        item = {"主体": sub, "描写": desc}
        if cmds:
            item["特殊指令"] = cmds
        out.append(item)
    return out

def _build_inn(slot):
    """客栈界面数据：中/上/奢三等级（每刻单价/体力时辰/气血内力比例）+ 主控金钱。
    inn-ui 强制休息 4 时辰（32刻），差不展示（露宿走 GM 自然语言指令）。"""
    player = (sm.read_meta(slot) or {}).get("角色名")
    pc = _read_char(slot, player) if player else None
    money = int(pc.get("铜钱", pc.get("银两", 0)) or 0) if pc else 0
    cur = es.get(slot, "当前位置") or ""
    _, _, scene = cur.partition("·")
    tiers = []
    for t in _INN_TIERS:
        cfg = _REST_TIERS[t]
        tiers.append({"等级": t, "每刻单价": cfg["每刻单价"], "体力每时辰": cfg["体力"],
                      "气血内力比例": cfg["气血比例"], "时长": 32})  # inn-ui 固定4时辰
    return {"界面": "inn-ui", "场景": scene or "客栈", "金钱": money, "等级": tiers}

def _shop_key(slot, seller):
    """商人货架缓存键：扁平「区域-地点-卖家名」（当前位置无地点后缀时地点段留空）。"""
    parts = (es.get(slot, "当前位置") or "").split("·")
    region, place = parts[0], (parts[1] if len(parts) > 1 else "")
    return f"{region}-{place}-{seller}"

def _grade_name(grade):
    """品级数字 → 品名；None 返回 None，未知品级回退为 str(数字)。"""
    if grade is None:
        return None
    return _GRADE_NAMES.get(int(grade), str(grade))

def _item_full(name, count):
    """据物品名 + 数量，从物品库补全为完整概要 dict。物品库无记录则仅留名称/数量。"""
    entry = {"名称": name, "数量": count}
    rec = dq.get("物品", name)
    if rec:
        for k in _ITEM_DETAIL_FIELDS:
            if k in rec:
                entry[k] = rec[k]
        if "品级" in entry:
            entry["品名"] = _grade_name(entry["品级"])
    return entry

def _build_trade_buy(slot, seller, merchant=False, tags=None):
    """购买界面数据：卖家货架（经 merchant_offer，含商人货架缓存）。每项含 名称/数量/类型/子类型/品级/价格/描述。"""
    offer = merchant_offer(slot, seller, merchant=merchant, tags=tags)
    buyer = (sm.read_meta(slot) or {}).get("角色名")
    buyer_char = _read_char(slot, buyer) if buyer else None
    money = buyer_char.get("铜钱", buyer_char.get("银两", 0)) if buyer_char else 0
    return {"界面": "trade-buy-ui", "卖家": seller, "商人": merchant,
            "买家": buyer, "金钱": money, "货架": offer.get("售卖", []), "来源": offer.get("来源")}

def _build_trade_sell(slot, buyer, merchant=False):
    """出售界面数据：主控物品栏可售物品（按种类合并计数 + 估价）。买家为收购 NPC。
    每项含 名称/数量/类型/子类型/品级/价格/描述。"""
    seller = (sm.read_meta(slot) or {}).get("角色名")
    seller_char = _read_char(slot, seller) if seller else None
    money = seller_char.get("铜钱", seller_char.get("银两", 0)) if seller_char else 0
    bag = seller_char.get("物品") or [] if seller_char else []
    counts, order = {}, []
    for it in bag:
        nm = it if isinstance(it, str) else (it.get("名称") if isinstance(it, dict) else None)
        if not nm:
            continue
        if nm not in counts:
            order.append(nm)
            counts[nm] = 0
        counts[nm] += 1
    items = []
    for nm in order:
        rec = dq.get("物品", nm) or {}
        entry = {"名称": nm, "数量": counts[nm]}
        for k in _ITEM_DETAIL_FIELDS:
            if k in rec:
                entry[k] = rec[k]
        if "品级" in entry:
            entry["品名"] = _grade_name(entry["品级"])
        items.append(entry)
    return {"界面": "trade-sell-ui", "买家": buyer, "商人": merchant,
            "卖家": seller, "金钱": money, "可售物品": _sort_items(items)}

def _sort_items(items):
    """物品列表按 (类型, 子类型, 品级) 排序；None/缺省字段排末尾。原位返回排序后列表。"""
    def key(e):
        t = e.get("类型") or ""
        s = e.get("子类型") or ""
        p = e.get("品级")
        p = 0 if p is None else p
        return (t, s, p)
    return sorted(items, key=key)

def merchant_offer(slot, seller, merchant=False, tags=None):
    """取卖家可售物品（封装 trade.seller_offer + 商人货架缓存）。

    · 非商人 → 直接调 trade.seller_offer，不缓存。
    · 商人 → 查 merchant.json 当前「区域·地点」下该卖家的货架记录：
        - 无记录 → 调 trade 生成货架并写回（仅记物品名+数量+上架时间）。
        - 有记录且 上架时间%960 == 当前时间%960 → 据缓存的库存从物品库补全详细字段后返回。
        - 有记录但跨换货周期 → 调 trade 重新生成并写回。
    tags：种类标签，单字符串或列表（多标签或关系），透传给 trade。
    返回 {"售卖": [物品概要...], "来源": "缓存"|"新生成"}。
    """
    _set_slot(slot)  # trade 经 dao 读物品库/角色，需先重定向数据目录

    if not merchant:
        return {"售卖": _sort_items(td.seller_offer(seller, merchant=False, tags=tags)),
                "来源": "新生成"}

    cur_time = int(es.get(slot, "当前时间", 0) or 0)
    key = _shop_key(slot, seller)
    data = sm.read_merchant_cache(slot)
    rec = data.get(key)
    if rec and rec.get("上架时间") is not None \
            and rec.get("上架时间") % _MERCHANT_PERIOD == cur_time % _MERCHANT_PERIOD \
            and "库存" in rec:
        offer = [_item_full(name, cnt) for name, cnt in rec["库存"].items() if cnt > 0]
        return {"售卖": _sort_items(offer), "来源": "缓存"}

    offer = td.seller_offer(seller, merchant=True, tags=tags)
    # 仅缓存物品名（去反引号）与数量
    stock = {}
    for e in offer:
        nm = e["名称"].strip("`")
        stock[nm] = int(e.get("数量", 1) or 1)
    data[key] = {"上架时间": cur_time, "库存": stock}
    sm.write_merchant_cache(slot, data)
    return {"售卖": _sort_items(offer), "来源": "新生成"}

def merchant_buy(slot, buyer, seller, item, count=1, merchant=False, price=None):
    """玩家向 NPC 购买物品：扣买家铜钱、物品入买家物品栏，并据身份扣卖方库存。

    · 个人身份（merchant=False）：卖家须为落盘 NPC（有实体）。无实体则购买失败，提示先建号
      （经 save_manager write-char，人设/物品栏由 GM 拟定，符自创角色规则）。落盘 NPC 从其
      物品栏扣减该物、铜钱增收；物品栏不足或无该物则购买失败。
    · 商人身份（merchant=True）：从 merchant.json 当前「区域·地点」下该卖家货架库存扣减
      该物品数量；货架无该物或库存不足则购买失败。商人 NPC 不记铜钱。

    item：物品名（不带反引号）；count：购买数量（≥1）。
    price：单价（铜钱），由 GM 据物品预设价格×关系度裁定后传入；缺省取物品库预设价格。
    返回 {"ok": bool, "msg": str, "变更": str, "铜钱": <买家剩余铜钱>}。
    """
    _set_slot(slot)
    count = int(count) if count else 1
    if count < 1:
        return {"ok": False, "msg": "购买数量须≥1"}
    rec = dq.get("物品", item)
    if not rec:
        return {"ok": False, "msg": f"未找到物品【{item}】"}
    unit = int(price) if price is not None else int(rec.get("价格", 0) or 0)
    total = unit * count

    buyer_char = _read_char(slot, buyer)
    if not buyer_char:
        return {"ok": False, "msg": f"未找到买家角色【{buyer}】"}
    copper = int(buyer_char.get("铜钱", buyer_char.get("银两", 0)) or 0)
    if copper < total:
        return {"ok": False, "msg": f"铜钱不足（持有{copper}，需{total}）"}

    # 扣卖方库存
    if merchant:
        # 商人：扣 merchant.json 货架库存（{物品名: 剩余数量}）
        data = sm.read_merchant_cache(slot)
        shop = data.get(_shop_key(slot, seller))
        if not shop or "库存" not in shop:
            return {"ok": False, "msg": f"【{seller}】当前无货架（请先调 merchant_offer 取数）"}
        stock = int(shop["库存"].get(item, 0) or 0)
        if stock <= 0:
            return {"ok": False, "msg": f"【{seller}】货架无【{item}】"}
        if stock < count:
            return {"ok": False, "msg": f"【{seller}】货架【{item}】库存不足（余{stock}，需{count}）"}
        if stock - count <= 0:
            del shop["库存"][item]
        else:
            shop["库存"][item] = stock - count
        sm.write_merchant_cache(slot, data)
    else:
        # 个人：卖家须有实体，从落盘 NPC 物品栏扣减、铜钱增收
        seller_char = _read_char(slot, seller)
        if not seller_char:
            return {"ok": False, "msg": f"卖家【{seller}】无实体，请先经 write-char 建号后再交易"}
        inv = seller_char.setdefault("物品", [])
        if inv.count(item) < count:
            return {"ok": False, "msg": f"【{seller}】物品栏【{item}】不足"}
        for _ in range(count):
            inv.remove(item)
        seller_char["铜钱"] = int(seller_char.get("铜钱", seller_char.get("银两", 0)) or 0) + total
        _write_char(slot, seller, seller_char)

    # 扣买家铜钱、物品入买家物品栏
    buyer_char["铜钱"] = copper - total
    buyer_char.setdefault("物品", []).extend([item] * count)
    _write_char(slot, buyer, buyer_char)
    mode = "商人" if merchant else "个人"
    return {"ok": True, "msg": f"购买{item}×{count}（{mode}，{total}铜钱）",
            "变更": f"获得 {item}×{count}，铜钱 -{total}",
            "铜钱": buyer_char["铜钱"]}

def merchant_sell(slot, seller, buyer, item, count=1, merchant=False, price=None):
    """玩家向 NPC 出售物品：玩家物品栏减、铜钱加；NPC（买家）铜钱减、物品入栏。

    · 个人身份（merchant=False）：买家须为落盘 NPC，从其铜钱扣款、物品入其物品栏；
      买家铜钱不足则出售失败。
    · 商人身份（merchant=True）：商人铜钱视为充足，物品补入 merchant.json 货架库存，
      商人 NPC 不记铜钱、不入物品栏。
    seller 在此为「售出方」（即玩家主控），buyer 为「收购方 NPC」。
    item：物品名；count：数量(≥1)；price：单价(铜钱)，缺省取物品库预设价。
    返回 {"ok": bool, "msg": str, "变更": str, "铜钱": <玩家剩余铜钱>}。
    """
    _set_slot(slot)
    count = int(count) if count else 1
    if count < 1:
        return {"ok": False, "msg": "出售数量须≥1"}
    rec = dq.get("物品", item)
    if not rec:
        return {"ok": False, "msg": f"未找到物品【{item}】"}
    unit = int(price) if price is not None else int(rec.get("价格", 0) or 0)
    total = unit * count

    player = _read_char(slot, seller)
    if not player:
        return {"ok": False, "msg": f"未找到售出方角色【{seller}】"}
    inv = player.get("物品") if isinstance(player.get("物品"), list) else []
    if inv.count(item) < count:
        return {"ok": False, "msg": f"物品栏【{item}】不足（{inv.count(item)}，需{count}）"}

    if merchant:
        # 商人：物品补入收购方（buyer）当前「区域·地点」的货架库存，不记铜钱
        data = sm.read_merchant_cache(slot)
        shop = data.setdefault(_shop_key(slot, buyer),
                               {"上架时间": int(es.get(slot, "当前时间", 0) or 0), "库存": {}})
        shop.setdefault("库存", {})
        shop["库存"][item] = int(shop["库存"].get(item, 0) or 0) + count
        sm.write_merchant_cache(slot, data)
    else:
        # 个人：买家须有实体，扣其铜钱、物品入其栏
        buyer_char = _read_char(slot, buyer)
        if not buyer_char:
            return {"ok": False, "msg": f"买家【{buyer}】无实体，请先经 write-char 建号后再交易"}
        bc_copper = int(buyer_char.get("铜钱", buyer_char.get("银两", 0)) or 0)
        if bc_copper < total:
            return {"ok": False, "msg": f"【{buyer}】铜钱不足（持有{bc_copper}，需{total}）"}
        buyer_char["铜钱"] = bc_copper - total
        buyer_char.setdefault("物品", []).extend([item] * count)
        _write_char(slot, buyer, buyer_char)

    # 玩家物品栏减、铜钱加
    for _ in range(count):
        inv.remove(item)
    player["物品"] = inv
    player["铜钱"] = int(player.get("铜钱", player.get("银两", 0)) or 0) + total
    _write_char(slot, seller, player)
    mode = "商人" if merchant else "个人"
    return {"ok": True, "msg": f"出售{item}×{count}（{mode}，{total}铜钱）",
            "变更": f"售出 {item}×{count}，铜钱 +{total}",
            "铜钱": player["铜钱"]}

def _gm_autosave_hint(slot):
    """自动存档回合返回的 GM参考：提示已自动存档。"""
    return {"提示": "已自动存档。经历概括 / 线索栏 已随 judge 顶层透出（全量），GM 据此做周期回顾即可。"}

def _region_info(slot, explore):
    """当前所在地点 + 该区域的已知场景图 + 区域人物。
    仅 go 隐藏 界面（GM 将下调 judge）的返回携带。"""
    pos = explore.get("当前位置") or ""
    region = pos.split("·")[0] if pos else ""
    if not region:
        return {}
    return {"当前所在地点": pos,
            "区域": region,
            "区域场景": sc.merged_scenes(slot, region),
            "区域人物": sc.scene_chars(slot, region, pos.split("·", 1)[1])}

def _inject_narrative(base, results):
    """汇总结算数组里的「当前剧情」「场景要素」为 base 顶层字段（供渲染），并从结算条目剔除，
    避免纯叙事混入状态变更结果。judge 路径叙事由顶层入参直入 base，不经此函数。"""
    plot = [r.get("当前剧情") for r in results if r.get("当前剧情")]
    if plot:
        base["剧情描写"] = "\n\n".join(plot)
    elements = [e for r in results if r.get("场景要素") for e in r["场景要素"]]
    if elements:
        base["场景要素"] = elements
    for r in results:
        r.pop("当前剧情", None)
        r.pop("场景要素", None)

def _build_clue_data(explore):
    """构造 clue-ui 数据：经历概括 + 线索栏（进行中/已关闭）。纯读 explore。"""
    raw = explore.get("任务摘要及进度") or []
    clues = [c for c in raw if isinstance(c, dict) and c.get("名称")]
    ongoing, closed = [], []
    for c in clues:
        entry = {
            "名称": c.get("名称"),
            "进展节点": [
                {"描述": n.get("描述", ""), "奖励": n.get("奖励")}
                for n in (c.get("进展节点") or []) if isinstance(n, dict)
            ],
        }
        (closed if c.get("关闭") else ongoing).append(entry)
    data = {"界面": "clue-ui", "进行中": ongoing, "已关闭": closed}
    if explore.get("经历概括") is not None:
        data["经历概括"] = explore.get("经历概括")
    return data

def _build_exploration_data(slot, ctx):
    """构造 exploration-ui 数据：_build_state 状态 + 叙事字段（剧情描写/场景要素/经历概括/线索栏）。
    纯读盘取数：叙事从 narrative（judge 顶层，已落 explore）或 explore（磁盘最终态）取。
    go 路径的 results 叙事由 _build_response 的 _inject_narrative 注入 base，本函数从 explore 读覆盖（同源一致）。"""
    ctx = ctx or {}
    data = {"界面": "exploration-ui"}
    data.update(_build_state(slot))
    explore = ctx.get("explore") or es.get_all(slot) or {}
    narrative = ctx.get("narrative") or {}
    # 剧情描写/场景要素：narrative（judge）优先，否则 explore（go 路径已落盘）
    plot = narrative.get("当前剧情")
    if plot is None:
        plot = explore.get("当前剧情")
    if plot is not None:
        data["剧情描写"] = plot
    elements = narrative.get("场景要素")
    if elements is None:
        elements = _norm_elements(explore.get("场景要素") or [])
    if elements:
        data["场景要素"] = elements
    # 区域人物：由 _build_state 提供（当前区域可登场的预设角色），不在此重复
    # 经历概括/线索栏：仅显式请求时带（加载存档/judge 自动存档），返回游戏/保存游戏 不带
    if ctx.get("with_summary"):
        if explore.get("经历概括") is not None:
            data["经历概括"] = explore.get("经历概括")
        if explore.get("任务摘要及进度") is not None:
            data["线索栏"] = explore.get("任务摘要及进度")
    return data

def _ctx_role(slot, ctx):
    """从 ctx.action 取 role，缺省回退主控名（meta.角色名）。"""
    a = (ctx or {}).get("action", {}) or {}
    return a.get("角色") or (sm.read_meta(slot) or {}).get("角色名")

def _ctx_bag_action(slot, ctx):
    """bag-ui 的筛选 action：使用物品路径注入 适用场合=世界，查看背包路径按 action 原样。"""
    a = (ctx or {}).get("action", {}) or {}
    if a.get("类型") == "使用物品":
        return {**a, "适用场合": "世界"}
    return a

def build_ui(slot, ui_id, ctx=None):
    """按界面id构造该界面渲染所需的全部数据字段（含 界面 字段本身）。
    纯取数/拼装层：不做任何结算与落盘，只从已落盘的最终状态读数。
    ctx 承载取数所需上下文：{action, explore, results, narrative, error, bt_data}。
    返回 dict，含 界面 字段及该界面数据；构造失败回退 exploration-ui+错误（沿用现有 _build_* 语义）。
    公共字段（saved/剩余/结算/槽位）由调用方 _build_response 合并，本函数只产界面相关字段。"""
    ctx = ctx or {}
    # message-ui：提示来自 error 或 action.提示 或固定串；删除存档附 删除槽位
    if ui_id == "message-ui":
        a = ctx.get("action", {}) or {}
        data = {"界面": "message-ui"}
        if ctx.get("error"):
            data["提示"] = ctx["error"]
        elif a.get("类型") == "非法指令":
            data["提示"] = a.get("提示") or "指令不合法或信息不足，请重新输入。"
        elif a.get("类型") == "删除存档":
            data["提示"] = "存档已删除"
        else:
            data["提示"] = ctx.get("error") or "指令不合法或信息不足，请重新输入。"
        for r in (ctx.get("results") or []):
            if r.get("槽位") is not None:
                data["删除槽位"] = r["槽位"]
                break
        return data
    # title-ui / save-ui：从结算载体提取界面字段
    if ui_id in ("title-ui", "save-ui"):
        data = {"界面": ui_id}
        keys = ("存档列表",) if ui_id == "save-ui" else (
            "标题状态", "版本", "存档列表", "创建草稿", "剩余点数",
            "初始武学列表", "武学详情", "属性说明", "校验提示",
        )
        for r in (ctx.get("results") or []):
            for key in keys:
                if r.get(key) is not None:
                    data[key] = r[key]
        return data
    # gm_error 的 exploration-ui：状态 + 错误（无叙事）
    if ui_id == "exploration-ui" and ctx.get("error"):
        data = {"界面": "exploration-ui"}
        data.update(_build_state(slot))
        data["错误"] = ctx["error"]
        return data
    # battle-*：bt_data 已是完整界面数据，直接返回
    if ui_id in ("battle-ui", "battle-end-ui", "exploration-battle-ui"):
        bt = ctx.get("bt_data")
        return bt if bt else {"界面": ui_id}
    builder = _UI_BUILDERS.get(ui_id)
    if not builder:
        return {"界面": ui_id}
    return builder(slot, ctx)

def _resolve_ui_id(valid, results, error, gm_error):
    """据本轮 action 判定应渲染的界面id（纯判定，不构造数据）。
    返回 ui_id 字符串；无界面（交 GM 推演）返回 None。与数据构造解耦。"""
    if error:
        return "exploration-ui" if gm_error else "message-ui"
    if len(valid) != 1:
        return None
    a = valid[0]
    t = a.get("类型")
    # 配置类：打开/结算均回对应子界面
    if t == "配置武学":
        return "wuxue-ui"
    if t == "配置装备":
        return "equip-ui"
    if t == "配置物品":
        return "item-ui"
    if t == "武学精进":
        return "wuxue-list-ui" if not a.get("武学") else "mastery-ui"
    if t == "角色信息" and a.get("角色"):
        return "character-ui"
    if t == "查看背包":
        return "bag-ui"
    if t == "查看地图":
        return "map-ui"
    if t == "查看线索":
        return "clue-ui"
    if t == "武学列表" and a.get("角色"):
        return "wuxue-list-ui"
    # 显式界面类
    if t in ("开始游戏", "标题-操作"):
        return "title-ui"
    if t == "存档列表":
        return "save-ui"
    if t == "删除存档":
        return "message-ui"
    if t == "非法指令":
        return "message-ui"
    if t in ("加载存档", "返回游戏", "保存游戏"):
        return "exploration-ui"
    # 纯机械结算类（带参数结算，回 exploration-ui 刷新）
    if (t == "使用物品" and a.get("物品")) or (t in ("购买", "出售") and a.get("物品")):
        return "exploration-ui"
    # 打开界面类（无参数，不消耗）
    if t == "使用物品" and not a.get("物品"):
        return "bag-ui"
    if t in ("购买", "出售") and not a.get("物品"):
        return "trade-buy-ui" if t == "购买" else "trade-sell-ui"
    if t == "远行（舟车）" and not a.get("目的地"):
        return "travel-ui"
    # 休息：免费=False 且缺等级/时长 → inn-ui；其余（带齐或免费缺参）→ 由 handler 处理（结算或报错）
    if t == "休息" and a.get("免费") is not True and not (a.get("等级") and a.get("时长")):
        return "inn-ui"
    # 默认：行为类结算 → 无界面，交 GM 推演
    return None

def _build_response(slot, valid, saved, 剩余, results, error=None, gm_error=False):
    """薄封装：拼公共字段 + 判定 ui_id + 调 build_ui 取界面数据。
    结算与落盘须在调用前完成（build_ui 只取数）。返回 {界面, saved, 剩余, 结算, 槽位, ...界面数据, 错误?}。
    error/gm_error：gm_error=True 表 GM 结算错误→回 exploration-ui+错误（状态照常）；否则 message-ui。"""
    # 建档：state_slot 取 results 中的新建slot（落点/时辰在新 slot），槽位切到新档
    state_slot = slot
    for r in results:
        if r.get("新建slot"):
            state_slot = r["新建slot"]
            break
    base = {"saved": saved, "剩余": 剩余, "结算": results, "槽位": state_slot}
    for r in results:
        if r.get("next_slot") is not None:
            base["next_slot"] = r["next_slot"]
        if r.get("错误码"):
            base["错误码"] = r["错误码"]
    _inject_narrative(base, results)  # 汇总结算里的叙事字段为顶层（旧档/内部调用仍可能带）
    # 结算条目中携带的 GM参考（如主动移动掷随机事件提示）上提顶层并从结算剔除
    #（非状态变更，不混入状态提示）；与自动存档提示合并为同一条。
    # 剔除后无内容（无 msg/变更）的载体条目一并移出结算，避免渲染空行
    hints = []
    kept = []
    for r in results:
        h = r.pop("GM参考", None)
        if h:
            hints.append(h)
            if not r.get("msg") and not r.get("变更"):
                continue
        kept.append(r)
    results[:] = kept
    if saved:
        hints.append(_gm_autosave_hint(state_slot)["提示"])
    if hints:
        base["GM参考"] = {"提示": "；".join(hints)}
    ui_id = _resolve_ui_id(valid, results, error, gm_error)
    if ui_id is None:
        # 无界面：交 GM 推演。仍带 _build_state 状态数据供前端兜底/日志
        base.update(_build_state(state_slot))
        return base
    ctx = {"action": valid[0] if valid else {}, "results": results, "error": error}
    # 加载存档：带经历概括/线索栏（从 results 读档快照）
    if valid and valid[0].get("类型") == "加载存档":
        ctx["with_summary"] = True
    ui_data = build_ui(state_slot, ui_id, ctx)
    # build_ui 产 exploration-ui 时已含 _build_state；其余子界面数据并入
    # message-ui/exploration-ui(gm_error) 的错误已由 build_ui 注入
    base.update(ui_data)
    if "界面" in base:
        base["渲染模式"] = render_mode()
        attach_render_text(base)
    return base

# 界面分发表：ui_id → 构造函数 (slot, ctx) → dict（含 界面 字段）。
# 纯取数/拼装，无结算无落盘。复用现有 _build_* 函数。
_UI_BUILDERS = {
    "exploration-ui": lambda slot, ctx: _build_exploration_data(slot, ctx),
    "wuxue-ui": lambda slot, ctx: _build_wuxue(slot, _ctx_role(slot, ctx)),
    "wuxue-list-ui": lambda slot, ctx: _build_wuxue_list(slot, _ctx_role(slot, ctx)),
    "equip-ui": lambda slot, ctx: _build_equip(slot, _ctx_role(slot, ctx)),
    "item-ui": lambda slot, ctx: _build_item(slot, _ctx_role(slot, ctx)),
    "character-ui": lambda slot, ctx: _build_character(slot, (ctx or {}).get("action", {}).get("角色")),
    "travel-ui": lambda slot, ctx: _build_travel(slot),
    "inn-ui": lambda slot, ctx: _build_inn(slot),
    "bag-ui": lambda slot, ctx: _build_bag(slot, _ctx_role(slot, ctx), _ctx_bag_action(slot, ctx)),
    "trade-buy-ui": lambda slot, ctx: _build_trade_buy(slot, (ctx or {}).get("action", {}).get("卖家"), bool((ctx or {}).get("action", {}).get("商人")), (ctx or {}).get("action", {}).get("标签")),
    "trade-sell-ui": lambda slot, ctx: _build_trade_sell(slot, (ctx or {}).get("action", {}).get("买家"), bool((ctx or {}).get("action", {}).get("商人"))),
    "map-ui": lambda slot, ctx: sc.build_map(slot, (ctx or {}).get("action", {}),
        (ctx.get("explore") if ctx and ctx.get("explore") else (es.get_all(slot) or {})),
        _resolve_region, _station_type),
    "clue-ui": lambda slot, ctx: _build_clue_data(
        (ctx.get("explore") if ctx and ctx.get("explore") else (es.get_all(slot) or {}))),
    "mastery-ui": lambda slot, ctx: _build_mastery(slot, _ctx_role(slot, ctx), (ctx or {}).get("action", {}).get("武学")),
}

