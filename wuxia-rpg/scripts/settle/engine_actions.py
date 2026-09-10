#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from collections import deque
"""engine actions 层(由 engine.py 拆分)。"""
import os, sys
import json
from world import character_ops as co
from common import dao as dq
from world import mastery as ms
from store import save_manager as sm
from store import battle_runtime as br
from combat import battle as bt
from common import status_manager as sm_status
from world import scene as sc
from store import explore_store as es
from settle import engine_state as est

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from settle.engine_io import _build_state, _clear_battle_tmp, _derive_caps, _ensure_data_dir, _load_map, _read_char, _resolve_party, _resolve_region, _write_char
from store.battle_last import read_battle_last as _read_battle_last, write_battle_last as _write_battle_last
from settle.engine_fields import _FIELD_HANDLERS, _apply_mastery, _carry_item_op, _carry_skill_op, _chg_carry_item, _chg_carry_skill, _chg_equip, _chg_party, _chg_xinfa
from settle.engine_ui import _REST_TIERS, _STATION_PRICE, _build_inn, _character_detail, _norm_elements, merchant_buy, merchant_sell
from settle.title_flow import build_character, handle_title_action

# 行为类型 → (体力消耗, 时间消耗(刻))；休息/远行（徒步/舟车）/战斗 特殊处理，不在此表
_ACTION_STAMINA = {"攻击": 1, "使用物品": 1, "购买": 2, "出售": 2, "遣散": 1, "其他行为": 4, "交谈观察": 1, "赠与物品": 1}

_ACTION_TIME = {"攻击": 1, "使用物品": 1, "购买": 2, "出售": 2, "遣散": 1, "其他行为": 2, "交谈观察": 1, "赠与物品": 1}

# 战斗整场耗时耗力：体力 20、时间 8 刻，战斗结束时 GM 在 judge 战后处置带
# {类型:战斗-结束} 条目，由 _apply_changes 自动结算（GM 不必手传体力/时间条目）
_BATTLE_STAMINA = 20

_BATTLE_TIME = 8

# 徒步远行单条边消耗（体力/刻）：路径每条边按此扣减
_WALK_STAMINA_PER_EDGE = 5

_WALK_TIME_PER_EDGE = 4

def _apply_stamina(slot, explore, c):
    """体力（队伍级，存 explore.json）：设/加，取 diff，夹取 [0, STAMINA_MAX]。
    直接操作 explore dict（从 read_explore 读、最终 write_explore 落盘）。"""
    try:
        val = int(c.get("值", 0))
    except (TypeError, ValueError):
        return {"ok": False, "msg": "体力变化缺值或非整数"}
    op = c.get("操作", "加")
    if op != "设" and val == 0:
        return {"ok": False, "msg": "体力变更目前传入0值，请GM重新斟酌更换成非0值或取消该变更"}
    old = int(explore.get("体力", 0) or 0)
    newv = val if op == "设" else max(0, old + val)
    newv = max(0, min(sm.STAMINA_MAX, newv))
    explore["体力"] = newv
    delta = newv - old
    sign = "+" if delta >= 0 else ""
    return {"ok": True, "msg": f"体力 {old}→{newv}", "变更": f"体力{sign}{delta}"}

def _advance_time(slot, explore, delta):
    """推进当前时间（刻）：直接操作 explore dict。返回推进结果条目（含旧/新时刻字符串）。"""
    old = int(explore.get("当前时间", 0) or 0)
    newv = old + int(delta)
    explore["当前时间"] = newv
    return {"ok": True, "msg": f"时间 {sm.time_to_str(old)} → {sm.time_to_str(newv)}",
            "变更": f"时间推进{delta}刻"}

def _apply_arrive(slot, explore, c):
    """抵达：玩家移动 → 设 explore.当前位置；NPC 移动 → 设角色.人物位置。
    传 角色 则改 NPC 位置，否则改当前玩家位置。"""
    dest = c.get("位置") or c.get("目的地")
    if not dest:
        return {"ok": False, "msg": "抵达缺 位置/目的地"}
    name = c.get("角色")
    if name:
        pos = explore.get("人物位置")
        if not isinstance(pos, dict):
            pos = {}
        pos[name] = dest
        explore["人物位置"] = pos
        return {"ok": True, "msg": f"{name} 抵达 {dest}"}
    explore["当前位置"] = dest
    return {"ok": True, "msg": f"抵达 {dest}", "变更": f"抵达 {dest}"}

def _act_rest(slot, explore, action):
    """休息（合并原休息+投宿）：按 等级(露宿/简朴/中等/奢华) + 时长(刻) + 免费(bool,必传) 结算。
    免费=False 且缺等级/时长 → inn-ui（展示简朴/中等/奢华，不消耗）；
    免费=True 且缺等级/时长 → 报错（免费休息须传齐等级+时长）；
    传齐等级+时长 → 扣费用(每刻单价×时长，免费则0)+推进时间+恢复体力(整时辰×等级体力)+气血内力(上限×比例×时辰数)。
    不校验场景，全靠 GM 裁定等级/免费。"""
    tier = action.get("等级")
    rest = int(action.get("时长", 0) or 0)
    free = action.get("免费")
    if free is None:
        return [{"ok": False, "msg": "休息须传入 免费（bool）"}]
    free = bool(free)
    # 缺等级或时长：免费→报错；收费→打开 inn-ui
    if not tier or rest <= 0:
        if free:
            return [{"ok": False, "msg": "免费休息须传入完整 等级 和 时长"}]
        return [{"ok": True, "msg": "打开客栈界面", "界面数据": _build_inn(slot)}]
    if tier not in _REST_TIERS:
        return [{"ok": False, "msg": f"无此休息等级【{tier}】，可选：{'、'.join(_REST_TIERS)}"}]
    cfg = _REST_TIERS[tier]
    results = []
    # 扣费用（每刻单价×时长，免费则0）
    fee = 0 if free else cfg["每刻单价"] * rest
    if fee:
        player = (sm.read_meta(slot) or {}).get("角色名")
        if player:
            pc = _read_char(slot, player)
            if pc:
                copper = int(pc.get("铜钱", pc.get("银两", 0)) or 0)
                if copper < fee:
                    return [{"ok": False, "msg": f"铜钱不足（持有{copper}，需{fee}）"}]
                pc["铜钱"] = copper - fee
                _write_char(slot, player, pc)
        results.append({"ok": True, "msg": f"休息（{tier}）付 {fee}钱", "变更": f"铜钱-{fee}"})
    # 推进时间
    tr = _advance_time(slot, explore, rest)
    if tr.get("ok"):
        results.append(tr)
    # 体力恢复：整时辰档位（时长//8 × 等级体力每时辰）
    shichen = rest // 8
    recover = shichen * cfg["体力"]
    if recover:
        sr = _apply_stamina(slot, explore, {"操作": "加", "值": recover})
        if sr.get("ok"):
            results.append(sr)
    # 气血内力恢复：每时辰回上限×比例，累乘夹取上限（差等级比例0不回）
    if cfg["气血比例"] > 0 and shichen > 0:
        party = explore.get("队伍") if explore.get("队伍") else list(_resolve_party(slot))
        for name in party:
            ch = _read_char(slot, name)
            if not ch:
                continue
            cap_hp, cap_mp = _derive_caps(ch)
            if cap_hp:
                ch["气血上限"] = cap_hp
            if cap_mp:
                ch["内力上限"] = cap_mp
            hp_recover = int(cap_hp * cfg["气血比例"] * shichen)
            mp_recover = int(cap_mp * cfg["气血比例"] * shichen)
            if cap_hp and ch.get("气血", 0) < cap_hp:
                target = min(cap_hp, ch.get("气血", 0) + hp_recover)
                r = co.apply_hp(ch, {"操作": "设", "值": target})
                if r["ok"]:
                    _write_char(slot, name, ch)
                    results.append({"ok": True, "msg": f"{name} {r['变更']}", "变更": f"{name} {r['变更']}"})
            if cap_mp and ch.get("内力", 0) < cap_mp:
                target = min(cap_mp, ch.get("内力", 0) + mp_recover)
                r = co.apply_mp(ch, {"操作": "设", "值": target})
                if r["ok"]:
                    _write_char(slot, name, ch)
                    results.append({"ok": True, "msg": f"{name} {r['变更']}", "变更": f"{name} {r['变更']}"})
    return results

def _apply_action_cost(slot, explore, action):
    """通用行为类体力/时间扣除：按 _ACTION_STAMINA/_ACTION_TIME 表扣。返回结果列表。
    休息/远行/战斗 等特殊体力时间由各自 handler 处理，不走此函数。"""
    t = action.get("类型")
    results = []
    cost = _ACTION_STAMINA.get(t, 0)
    if cost:
        sr = _apply_stamina(slot, explore, {"操作": "加", "值": -cost})
        if sr.get("ok"):
            results.append(sr)
    tcost = _ACTION_TIME.get(t, 0)
    if tcost:
        tr = _advance_time(slot, explore, tcost)
        if tr.get("ok"):
            results.append(tr)
    return results

def _walk_path(slot, region, start, goal):
    """区域内场景连通图 BFS 寻路：返回 start→goal 的场景名列表（含两端）。
    图取基线∪覆盖层（sc.merged_scenes），按无向图处理（方位出口双向可达）。
    不可达 / 起点或终点不在图中 → 返回 None。"""
    graph = sc.merged_scenes(slot, region)
    adj = {}
    for scn, exits in (graph or {}).items():
        for nb in (exits or {}).values():
            if not nb:
                continue
            adj.setdefault(scn, set()).add(nb)
            adj.setdefault(nb, set()).add(scn)
    if not start or not goal or start not in adj or goal not in adj:
        return None
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for nb in adj.get(cur, ()):
            if nb not in prev:
                prev[nb] = cur
                q.append(nb)
    if goal not in prev:
        return None
    path, node = [], goal
    while node is not None:
        path.append(node)
        node = prev[node]
    path.reverse()
    return path

def _act_travel(slot, explore, action):
    """远行（徒步/舟车）：扣体力+推进时间+抵达目的地。
    远行（徒步）：区域内连通图 BFS 寻路，按路径边数扣体力/时间（1边=5体力4刻），抵达目的地。
    跨区域徒步报错（跨区走舟车经驿站）；不连通或已在目的地报错。
    远行（舟车）无 目的地 → 返回 travel-ui（当前驿站可达路线），不消耗；
    有目的地 → 据 map.json 邻接算直达耗时(天)+费用(耗时×驿站单价)，扣费+推进对应天数+体力补满+抵达。
    仅支持直达路线；非直达目的地（需换乘）报错。"""
    t = action.get("类型")
    dest = action.get("目的地")
    if t == "远行（舟车）":
        # 须在驿站/码头方可启程或查看路线：engine 据当前场景类型自查，无需 在驿站 参数
        cur_pos = explore.get("当前位置") or ""
        cur_region, _, cur_scene = cur_pos.partition("·")
        if sc.scene_type(slot, cur_region, cur_scene) != "驿站":
            return [{"ok": False, "msg": "需先至驿站/码头方可启程远行"}]
    if not dest:
        if t == "远行（舟车）":
            return [{"ok": True, "msg": "打开驿站界面"}]
        return [{"ok": False, "msg": "徒步远行须指定 目的地（区域内场景）"}]
    # 徒步远行：区域内连通图寻路，按路径边数扣体力/时间（1边=5体力4刻）。
    # 跨区域徒步报错（跨区走「远行（舟车）」经驿站）。
    walk_edges = None
    if t == "远行（徒步）":
        cur_pos = explore.get("当前位置") or ""
        cur_region, _, cur_scene = cur_pos.partition("·")
        if not cur_scene:
            return [{"ok": False, "msg": f"当前位置【{cur_pos}】无场景后缀，无法徒步寻路"}]
        # 目的地支持「区域·场景」或裸场景名；裸场景名（无「·」）时 dest_region 置空，
        # 仅以场景名寻路，避免裸名被误判为异区目的地。
        if "·" in dest:
            dest_region, _, dest_scene = dest.partition("·")
        else:
            dest_region, dest_scene = "", dest
        if dest_region and dest_region != cur_region:
            return [{"ok": False,
                     "msg": f"【{dest}】非当前区域【{cur_region}】，跨区域请经驿站走「远行（舟车）」"}]
        path = _walk_path(slot, cur_region, cur_scene, dest_scene)
        if not path:
            # 区分：终点不在场景图→不存在/名称错；在图但不连通→不连通
            known = (sc.merged_scenes(slot, cur_region) or {})
            if dest_scene not in known and not any(dest_scene in (e or {}).values()
                                                    for e in known.values()):
                return [{"ok": False, "msg": f"【{dest_scene}】地点不存在或名称错误"}]
            return [{"ok": False,
                     "msg": f"【{dest_scene}】与当前地点【{cur_scene}】不连通，徒步无法抵达"}]
        walk_edges = len(path) - 1
        if walk_edges == 0:
            return [{"ok": False, "msg": f"已在目的地【{dest_scene}】，无需远行"}]
        # 全程体力预检：当前体力 < 路径边数×单边消耗则打回（不落盘不扣费）
        need_st = walk_edges * _WALK_STAMINA_PER_EDGE
        cur_st = int(explore.get("体力", 0) or 0)
        if cur_st < need_st:
            return [{"ok": False,
                     "msg": f"体力不足（持有{cur_st}，全程{walk_edges}段需{need_st}），无法徒步前往【{dest_scene}】"}]
    results = []
    if t == "远行（舟车）":
        # 据 map 邻接查直达路线耗时与费用
        m = _load_map()
        nodes = m.get("节点", {})
        adj = m.get("邻接", {})
        cur = _resolve_region(explore.get("当前位置") or "", nodes)
        if cur is None:
            return [{"ok": False, "msg": "当前位置无对应驿站，无法启程"}]
        dest_region = _resolve_region(dest, nodes) or dest
        route = adj.get(cur, {}).get(dest_region)
        if route is None:
            return [{"ok": False, "msg": f"【{cur}】驿站无直达【{dest_region}】路线，需经他处换乘"}]
        days = int(route)
        stype = nodes.get(cur, "陆驿")
        fee = days * _STATION_PRICE.get(stype, 150)
        # 扣费用（主控铜钱）
        player = (sm.read_meta(slot) or {}).get("角色名")
        if player:
            pc = _read_char(slot, player)
            if pc:
                copper = int(pc.get("铜钱", pc.get("银两", 0)) or 0)
                if copper < fee:
                    return [{"ok": False, "msg": f"铜钱不足（持有{copper}，需{fee}）"}]
                pc["铜钱"] = copper - fee
                _write_char(slot, player, pc)
                results.append({"ok": True, "msg": f"付船资 {fee}钱", "变更": f"铜钱-{fee}"})
        sr = _apply_stamina(slot, explore, {"操作": "设", "值": sm.STAMINA_MAX})
        if sr.get("ok"):
            results.append(sr)
        tr = _advance_time(slot, explore, days * sm.TIME_UNITS_PER_DAY)
        if tr.get("ok"):
            results.append(tr)
    else:  # 徒步：按寻路边数扣减（1边=5体力4刻）
        cost_st = walk_edges * _WALK_STAMINA_PER_EDGE
        cost_t = walk_edges * _WALK_TIME_PER_EDGE
        sr = _apply_stamina(slot, explore, {"操作": "加", "值": -cost_st})
        if sr.get("ok"):
            results.append(sr)
        tr = _advance_time(slot, explore, cost_t)
        if tr.get("ok"):
            results.append(tr)
    # 抵达目的地补全「区域·场景」格式：dest 无场景后缀时补全前缀
    # 舟车跨区：落脚目的地所在区域的驿站出口场景；徒步同区：补当前区域前缀
    arrive_dest = dest
    if "·" not in (dest or ""):
        if t == "远行（舟车）":
            station = (sc.load_scenes().get("驿站出口", {}) or {}).get(dest_region)
            if station:
                arrive_dest = f"{dest_region}·{station}"
        else:  # 徒步同区：按当前区域补全前缀，避免落地为裸场景名致地图无法解析
            cur_region = (explore.get("当前位置") or "").split("·")[0]
            if cur_region:
                arrive_dest = f"{cur_region}·{dest}"
    ar = _apply_arrive(slot, explore, {"目的地": arrive_dest})
    results.append(ar)
    if ar.get("ok"):
        # 主动移动成功：附 GM参考，经 _build_response 上提顶层，提示 GM 掷随机事件
        results.append({"ok": True,
                        "GM参考": "玩家本次为主动移动（" + t + "）——应按随机事件规则掷骰判定旅途遭遇"})
    return results

def _act_use_item(slot, explore, action):
    """使用物品：据物品使用效果自动结算（扣物品+回气血/内力/体力/施加状态）。
    无 物品 参数 → 返回 bag-ui（按大世界可用筛选，不扣体力时间，纯浏览）；
    带 物品 → 行为类结算（扣1体力1刻）。适用场合校验：须大世界可用，否则 message-ui。"""
    name = action.get("物品")
    target = action.get("目标")
    if not name:
        # 无物品参数：打开背包界面（按大世界可用筛选），不消耗
        return [{"ok": True, "msg": "打开背包界面"}]
    rec = dq.get("物品", name)
    if not rec:
        return [{"ok": False, "msg": f"未找到物品【{name}】"}]
    if not dq.usable_in(rec, "世界"):
        return [{"ok": False, "msg": f"【{name}】非大世界可用物品（仅战斗可用）"}]
    # judge 复用效果结算：_judge_mode 不扣体力时间（代价由 GM 在 judge 状态变更新时单独补）
    results = [] if action.get("_judge_mode") else _apply_action_cost(slot, explore, action)
    # 目标默认主控
    if not target:
        target = (sm.read_meta(slot) or {}).get("角色名")
    if not target:
        return results + [{"ok": False, "msg": "使用物品缺目标（无主控）"}]
    ch = _read_char(slot, target)
    if not ch:
        return results + [{"ok": False, "msg": f"未找到目标角色【{target}】"}]
    inv = ch.get("物品")
    if not (isinstance(inv, list) and name in inv):
        return results + [{"ok": False, "msg": f"{target} 物品栏无【{name}】"}]
    eff = rec.get("使用效果", {}) or {}
    sub = rec.get("子类型") or ""
    # 扣物品
    inv.remove(name)
    results.append({"ok": True, "msg": f"消耗 {name}", "变更": f"消耗 {name}"})
    # 研读类：秘籍→武学习得/精进一层；技艺书→技艺累加（≤25 封顶）。
    # 据物品「适用场合」字段判定大世界可用（秘籍/技艺书=世界），GM 只传物品+目标，不感知分流。
    if sub.endswith("秘籍"):
        skill_name = rec.get("武学")
        if not skill_name:
            results.append({"ok": False, "msg": f"秘籍【{name}】缺 武学 字段", "_结算错误": True})
            _write_char(slot, target, ch)
            return results
        r = ms.book_advance(ch, skill_name)
        if not r.get("ok"):
            results.append({"ok": False, "msg": r["msg"], "_结算错误": True})
            _write_char(slot, target, ch)
            return results
        ch["武学"] = r["delta"]["武学"]
        results.append({"ok": True, "msg": f"{target} {r['msg']}", "变更": f"{target} {r['msg']}"})
    elif "技艺" in eff:
        yi_map = eff["技艺"] or {}
        if not isinstance(yi_map, dict) or not yi_map:
            results.append({"ok": False, "msg": f"技艺书【{name}】使用效果.技艺 格式非法", "_结算错误": True})
            _write_char(slot, target, ch)
            return results
        for yi_name, yi_val in yi_map.items():
            r = co.apply_yi(ch, {"名": yi_name, "值": int(yi_val)})
            if not r.get("ok"):
                results.append({"ok": False, "msg": r["msg"], "_结算错误": True})
                _write_char(slot, target, ch)
                return results
            results.append({"ok": True, "msg": f"{target} {r['变更']}", "变更": f"{target} {r['变更']}"})
    # 回气血
    hp = eff.get("回复气血")
    if hp:
        r = co.apply_hp(ch, {"操作": "加", "值": int(hp)})
        results.append({"ok": True, "msg": f"{target} {r['变更']}", "变更": f"{target} {r['变更']}"})
    # 回内力
    mp = eff.get("回复内力")
    if mp:
        _, cap_mp = _derive_caps(ch)
        old = ch.get("内力", 0) or 0
        newv = min(int(mp) + old, cap_mp) if cap_mp else int(mp) + old
        ch["内力"] = newv
        results.append({"ok": True, "msg": f"{target} 内力 {old}→{newv}", "变更": f"{target} 内力 {old}→{newv}"})
    # 回体力（食物）
    sta = eff.get("回复体力")
    if sta and explore:
        sr = _apply_stamina(slot, explore, {"操作": "加", "值": int(sta)})
        if sr.get("ok"):
            results.append(sr)
    # 施加状态（大世界施加，scene=大世界）
    st = eff.get("施加状态")
    if st:
        sid = st.get("id")
        dur = st.get("回合", 1)
        stacks = max(1, int(st.get("层数", 1)))
        for _ in range(stacks):
            sm_status.apply_status(ch, sid, dur, actor=ch, source=name, source_type="物品", scene="大世界")
        suffix = f"×{stacks}" if stacks > 1 else ""
        results.append({"ok": True, "msg": f"{target} 获得【{sm_status.buff_name_of(sid)}】{suffix}",
                        "变更": f"{target} 获得【{sm_status.buff_name_of(sid)}】{suffix}"})
    _write_char(slot, target, ch)
    return results

def _act_buy(slot, explore, action):
    """购买：向卖家买物品。行为类（扣2体力2刻）。
    无 卖家 → message-ui；有卖家无 物品 → trade-buy-ui（展示货架）；有卖家+物品 → 结算→exploration-ui。"""
    seller = action.get("卖家")
    item = action.get("物品")
    buyer = action.get("买家") or (sm.read_meta(slot) or {}).get("角色名")
    merchant = bool(action.get("商人"))
    tags = action.get("标签")
    if not seller:
        return [{"ok": False, "msg": "购买须指定 卖家"}]
    if not item:
        # 无物品：展示卖家货架（不消耗）
        return [{"ok": True, "msg": f"查看 {seller} 货架"}]
    count = int(action.get("数量", 1) or 1)
    price = action.get("价格")
    results = _apply_action_cost(slot, explore, action)
    r = merchant_buy(slot, buyer, seller, item, count=count, merchant=merchant, price=price)
    return results + ([r] if isinstance(r, dict) else r)

def _act_sell(slot, explore, action):
    """出售：向买家（收购NPC）售物品。行为类（扣2体力2刻）。
    无 买家 → message-ui；有买家无 物品 → trade-sell-ui（展示主控可售物品）；有买家+物品 → 结算→exploration-ui。"""
    buyer = action.get("买家")
    item = action.get("物品")
    seller = action.get("卖家") or (sm.read_meta(slot) or {}).get("角色名")
    merchant = bool(action.get("商人"))
    if not buyer:
        return [{"ok": False, "msg": "出售须指定 买家"}]
    if not item:
        # 无物品：展示主控可售物品（不消耗）
        return [{"ok": True, "msg": f"查看可售物品（收购方 {buyer}）"}]
    count = int(action.get("数量", 1) or 1)
    price = action.get("价格")
    results = _apply_action_cost(slot, explore, action)
    r = merchant_sell(slot, seller, buyer, item, count=count, merchant=merchant, price=price)
    return results + ([r] if isinstance(r, dict) else r)

def _act_gift(slot, explore, action):
    """赠与物品：将物品从「受赠者」与「赠送者物品栏」之间转物品。行为类（扣1体力1刻）。
    属于需 GM judge 的玩家主动行为：结束回世界界面判据是「GM 须下调 judge」。
    赠送者缺省主控；受赠者须已落盘（物品++ошибадение临时 NPC 未落盘拒收）。"""
    item = action.get("物品")
    target = action.get("受赠者")
    count = int(action.get("数量", 1) or 1)
    if count < 1:
        return [{"ok": False, "msg": "赠与数量须≥1"}]
    # 赠送者缺省主控，可显式传 买家 → 兼容店铺赠物或队伍成员代替
    giver = action.get("赠送者") or action.get("买家") or (sm.read_meta(slot) or {}).get("角色名")
    if not item:
        return [{"ok": False, "msg": "赠与物品须传入 物品"}]
    if not target:
        return [{"ok": False, "msg": "赠与物品须传入 受赠者"}]
    rec = dq.get("物品", item)
    if not rec:
        return [{"ok": False, "msg": f"未找到物品【{item}】"}]
    # 物品栏读事务区/盘
    g = _read_char(slot, giver)
    t = _read_char(slot, target)
    if not g:
        return [{"ok": False, "msg": f"未找到赠送者【{giver}】"}]
    if not t:
        return [{"ok": False, "msg": f"受赠者【{target}】未落盘"}]
    inv = g.get("物品")
    if not isinstance(inv, list) or inv.count(item) < count:
        return [{"ok": False, "msg": f"{giver} 物品栏【{item}】不足（持有{inv.count(item) if isinstance(inv,list) else 0}，需{count}）"}]
    results = _apply_action_cost(slot, explore, action)
    # 扣赠送者栏
    for _ in range(count):
        if item in inv:
            inv.remove(item)
    # 赠者详情记录
    g["_赠与记录"] = g.get("_赠与记录", []) + [{"物品": item, "数量": count, "受赠者": target}]
    # 补受赠者栏
    tinv = t.setdefault("物品", [])
    if not isinstance(tinv, list):
        t["物品"] = tinv = []
    tinv.extend([item] * count)
    _write_char(slot, giver, g)
    _write_char(slot, target, t)
    results.append({"ok": True, "msg": f"{giver} 把 {item}×{count} 赠给 {target}",
                    "变更": f"{giver} 赠与 {target} {item}×{count}"})
    return results

def _run_battle_func(slot, func, *args, **kw):
    """调用 battle.py 的函数（run_init/run_step），捕获其 stdout 的 JSON 输出并解析返回。
    battle.py 经 emit_battle_json print 一行 JSON，此处透传该 JSON 供 engine 返回 battle-ui。"""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(*args, **kw)
    out = buf.getvalue().strip()
    if not out:
        return {"界面": "battle-ui", "战报": "", "战局状态": {}}
    # battle.py 输出一行 JSON；取最后一行（防有多余输出）
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                import json
                return json.loads(line)
            except Exception:
                break
    return {"界面": "battle-ui", "战报": out, "战局状态": {}}

def _act_battle(slot, explore, action):
    """战斗-开始（judge 专属）：调 battle.py run_init 启动战斗，返回 battle-ui。战后经验/处决由 judge 处置落盘。
    操控方式决定受控角色(players)：
      玩家角色 → [主控]；我方全员 → side_a；AI自动 → []（纯AI推进，玩家观战）。
    缺省按 我方全员（向后兼容）。"""
    side_a = action.get("我方") or []
    side_b = action.get("敌方") or []
    allow_escape = bool(action.get("允许逃跑", False))
    ctrl = action.get("操控方式", "我方全员")
    player_name = (sm.read_meta(slot) or {}).get("角色名")
    if ctrl == "玩家角色":
        players = [player_name] if player_name else []
    elif ctrl == "AI自动":
        players = []
    else:  # 我方全员（缺省）
        players = list(side_a)
    names = list(side_a) + list(side_b)
    faction_map = {}
    for n in side_a:
        faction_map[n] = "我方"
    for n in side_b:
        faction_map[n] = "敌方"
    if ctrl == "AI自动":
        # AI自动：走纯 AI 整场（run_battle，300 回合上限超时判平局），整场打到底、无玩家界面
        bt_data = _run_battle_func(slot, bt.pure_ai, names, None, faction_map, slot,
                                   allow_escape=allow_escape)
    else:
        bt_data = _run_battle_func(slot, bt.run_init, names, players, None, faction_map, slot,
                                   allow_escape=allow_escape)
    bt_data["我方"] = side_a
    bt_data["敌方"] = side_b
    bt_data["允许逃跑"] = allow_escape
    bt_data["操控方式"] = ctrl
    return [], bt_data

def _act_battle_step(slot, explore, action, instruction):
    """战斗内行动：调 battle.py run_step 推进一回合，返回 battle-ui。配置类，不推进大世界。"""
    bt_data = _run_battle_func(slot, bt.run_step, instruction, slot)
    return [], bt_data

def _act_battle_skill(slot, explore, action):
    """战斗-使用武学：调 battle.py run_step('武学 <技能> <目标>')。"""
    skill = action.get("武学")
    target = action.get("目标")
    if not skill:
        return [{"ok": False, "msg": "战斗-使用武学须传入 武学"}]
    instr = f"武学 {skill}"
    if target:
        instr += f" {target}"
    return _act_battle_step(slot, explore, action, instr)

def _act_battle_item(slot, explore, action):
    """战斗-使用物品：调 battle.py run_step('使用 <物品> <目标>')。"""
    item = action.get("物品")
    target = action.get("目标")
    if not item:
        return [{"ok": False, "msg": "战斗-使用物品须传入 物品"}]
    instr = f"使用 {item}"
    if target:
        instr += f" {target}"
    return _act_battle_step(slot, explore, action, instr)

def _act_battle_rest(slot, explore, action):
    """战斗-休息：调 battle.py run_step('休息')。"""
    return _act_battle_step(slot, explore, action, "休息")

def _act_battle_flee(slot, explore, action):
    """战斗-逃跑：调 battle.py run_step('逃跑')。"""
    return _act_battle_step(slot, explore, action, "逃跑")

def _act_battle_surrender(slot, explore, action):
    """战斗-认输：调 battle.py run_step('认输')。"""
    return _act_battle_step(slot, explore, action, "认输")

def _act_battle_trigger(slot, explore, action):
    """战斗-触发：战前参战确认/操控选择界面。不跑战斗，返回 exploration-battle-ui：
    当前场景状态(供渲染 exploration 上半部分) + 双方名单 + 操控方式选项。
    玩家选定操控方式后，GM 据选项拼成 战斗-开始 action（带 操控方式）再调 engine。"""
    side_a = action.get("我方") or []
    side_b = action.get("敌方") or []
    allow_escape = bool(action.get("允许逃跑", False))
    player_name = (sm.read_meta(slot) or {}).get("角色名")
    party = explore.get("队伍") if explore else None
    # 队友 = 我方队伍中除主控外的人
    teammates = [n for n in (party or []) if n and n != player_name] if party else []
    has_teammate = len(teammates) > 0
    options = ["玩家角色", "AI自动"] if not has_teammate else ["玩家角色", "我方全员", "AI自动"]
    state = _build_state(slot)
    return [{"ok": True, "msg": "战前选择界面"}], {
        "界面": "exploration-battle-ui",
        "我方": side_a, "敌方": side_b, "允许逃跑": allow_escape,
        "主控": player_name, "有队友": has_teammate, "操控选项": options,
        "GM参考": "玩家选定操控方式后，复用上列 我方/敌方/允许逃跑 并带 操控方式 拼成 战斗-开始 条目，再调一次 engine judge 进入战斗（本界面仅战前选择，不算战斗进入）",
        **state,
    }

def _act_battle_advance(slot, explore, action):
    """战斗-推进（judge 专属）：把上一轮战斗操控 go 的结算打包成 battle-ui。

    战斗操控 go（战斗-使用武学等）已把规范战报与回合详情缓存进 battle_last.json；
    本条目只读取该底稿并附带兼容的结构化回合详情，不接受 GM 改写战报。
    """
    if "战报文本" in action:
        return [{"ok": False, "msg": "战斗-推进不再接受 战报文本；请删除该字段并重试，engine 会使用已缓存的规范战报"}]
    bt_data = _read_battle_last(slot)
    if bt_data is None:
        return [{"ok": False, "msg": "本轮无可推进的战斗（战斗操控 go 的结算未找到，须先执行战斗操控 go）"}]
    details = action.get("回合详情")
    if details is not None:
        bt_data["回合详情"] = details
    bt_data["界面"] = "battle-ui"
    _maybe_battle_end_ui(bt_data)  # 终局我方胜：推进的包出的界面改 battle-end-ui（带处决候选）
    return [], bt_data

def _maybe_battle_end_ui(bt_data):
    """终局我方胜 → battle-end-ui（处决裁定界面）：界面器重换并附 处决候选。

    候选=敌方中果定为败阵者（逃走者不得处决）。
    local import integrity：纯变换、原 key 不变；终局非我方胜时不动。"""
    st = (bt_data.get("战局状态") or {}).get("状态")
    if st not in ("我方胜", "敌方认输"):
        return
    enemy_names = []
    for r in (bt_data.get("战局状态") or {}).get("敌方") or []:
        n = str(r).split("：", 1)[0].strip()
        if n:
            enemy_names.append(n)
    战果 = bt_data.get("战果") or {}
    # 未逃走的敌方皆可裁（存活亦在胜方手中——如敌方认输了阵未走）；逃走者不得处决
    bt_data["处决候选"] = [{"名称": n, "状态": 战果.get(n, "败阵")} for n in enemy_names
                         if 战果.get(n) and 战果.get(n) != "逃走"]
    bt_data["界面"] = "battle-end-ui"

def _act_battle_execute(slot, explore, action):
    """战斗-处决（go 专属，终局我方胜时）：逐人记录玩家对未逃走敌方败阵者的处决决定。

    仅写回执到 battle_last.json（供 GM 判读/核对），**不落盘任何状态**——处决（死亡）、
    经验、战利品、体力时间等由 GM 在战后处置 judge 一并落盘。返回无界面。"""
    cached = _read_battle_last(slot)
    if cached is None:
        return [{"ok": False, "msg": "当前无待裁定处决的战斗（须先把战局打到我方胜的终局）"}]
    st = (cached.get("战局状态") or {}).get("状态")
    if st not in ("我方胜", "敌方认输"):
        return [{"ok": False, "msg": f"战斗-处决仅我方胜终局可用（当前战局状态：{st or '未知'}）"}]
    helper = dict(cached)
    _maybe_battle_end_ui(helper)
    cands = [c["名称"] for c in helper.get("处决候选") or []]
    decisions = action.get("处置")
    if not cands:
        # 敌方全逃走：无可裁对象，记空决定即可
        if decisions:
            return [{"ok": False, "msg": "获胜但敌方无在场败阵者（全逃走），无处决对象"}]
        decided = []
        kill = spare = "无"
    else:
        if not isinstance(decisions, list) or not decisions:
            return [{"ok": False, "msg": "战斗-处决须传入 处置 数组，逐人裁定：" + "、".join(cands)}]
        for d in decisions:
            if not isinstance(d, dict) or d.get("决定") not in ("杀", "放"):
                return [{"ok": False, "msg": "处置 每条须为 {角色, 决定(杀/放)}（可选 细节 供 GM 叙事参考）"}]
        got = [d.get("角色") for d in decisions]
        if sorted(got) != sorted(cands):
            return [{"ok": False, "msg": "处决须逐人裁定完整：待裁=" + "、".join(cands)
                          + "；你的覆盖=" + "、".join(str(x) for x in got)}]
        decided = decisions
        kill = "、".join(d["角色"] for d in decided if d["决定"] == "杀") or "无"
        spare = "、".join(d["角色"] for d in decided if d["决定"] == "放") or "无"
    cached["处决决定"] = decided
    _write_battle_last(slot, cached)
    return [{"ok": True, "msg": f"处决决定已记录（杀：{kill}；放：{spare}）。"
              "你 是作为 GM 裁决依据的记录，须由 GM 在战后处置 judge 一并落盘（处决/经验/战斗-结束/战利品）。"}]

def _act_dismiss(slot, explore, action):
    """遣散：转为 在队.离.遣散 变更，复用 _chg_party（自动算遣散费/扣铜钱或关系度）。"""
    name = action.get("角色")
    if not name:
        return [{"ok": False, "msg": "遣散须传入 角色"}]
    results = _apply_action_cost(slot, explore, action)
    return results + [_chg_party(slot, {"类型": "在队", "操作": "离", "角色": name, "原因": "遣散"})]

def _act_mastery(slot, explore, action):
    """武学精进。带 界面 直接渲染。
    无 武学 参数 → wuxue-list-ui（列出已习得武学供选择）；
    带 武学 且 操作:精进 → 直接结算精进（计入状态变更）→ exploration-ui；
    带 武学 无精进意图 → mastery-ui（查看该武学十境表）；
    带 武学 但等级已满(10境) 或 未习得 → message-ui。"""
    role = action.get("角色") or (sm.read_meta(slot) or {}).get("角色名")
    skill = action.get("武学")
    if not skill:
        # 无武学参数：列出已习得武学供选择
        if not role:
            return [{"ok": False, "msg": "精进须指定 角色"}]
        return [{"ok": True, "msg": "打开武学列表"}]
    # 校验武学是否习得、是否满级
    char = _read_char(slot, role)
    if not char:
        return [{"ok": False, "msg": f"未找到角色【{role}】"}]
    lvl = ms.get_learned_level(char, skill) or 0
    if lvl == 0:
        return [{"ok": False, "msg": f"尚未习得【{skill}】，无法精进"}]
    if lvl >= 10:
        return [{"ok": False, "msg": f"【{skill}】已达大成（第 10 境），无可精进"}]
    if action.get("操作") == "精进":
        return [_apply_mastery(slot, {"类型": "武学", "操作": "精进", "角色": role, "名": skill})]
    # 打开精进界面（查看该武学十境表）
    return [{"ok": True, "msg": "打开精进界面"}]

def _apply_changes(slot, explore, changes):
    """遍历执行 状态变更 数组（judge 行为数组中的一等条目）。由 judge 承担，交谈观察不再携带。
    失败结果标记 _结算错误=True，供 judge 整体回滚判定。"""
    results = []
    for c in changes:
        if not isinstance(c, dict):
            results.append({"ok": False, "msg": "非法状态变更条目", "_结算错误": True})
            continue
        kind = c.get("类型")
        if kind == "武学":
            r = _apply_mastery(slot, c)
        elif kind == "体力" and explore:
            r = _apply_stamina(slot, explore, c)
        elif kind == "时间" and explore:
            delta = c.get("值")
            if not isinstance(delta, int):
                r = {"ok": False, "msg": "时间变更须传入 值（整数刻数）"}
            elif delta == 0:
                r = {"ok": False, "msg": "时间变更目前传入0值，请GM重新斟酌更换成非0值或取消该变更"}
            else:
                r = _advance_time(slot, explore, delta)
        elif kind == "战斗-结束" and explore:
            # 战斗整场耗时耗力（体力-20/时间+8刻）：战后处置一条带过，GM 不必手传体力/时间条目
            for r0 in (_apply_stamina(slot, explore, {"操作": "加", "值": -_BATTLE_STAMINA}),
                       _advance_time(slot, explore, _BATTLE_TIME)):
                if not r0.get("ok"):
                    r0["_结算错误"] = True
                results.append(r0)
            continue
        elif kind == "抵达" and explore:
            r = _apply_arrive(slot, explore, c)
        elif kind == "登记场景":
            # 新场景随 judge 状态变更带入；写入本轮暂存区，commit 阶段落盘（支持整轮回滚）
            r = sc.register_scene(slot, c, est._SCENE_STAGED, est._SCENE_TYPE_STAGED)
        elif kind == "隔离地点":
            # 将已登记地点重置为孤岛（清空出入口及反向边）；写入本轮暂存区，commit 阶段落盘
            r = sc.isolate_scene(slot, c, est._SCENE_STAGED)
        elif kind == "线索" and explore:
            r = _apply_clue(slot, explore, c)
        elif kind == "使用物品":
            # 复用 go 使用物品 的效果结算（大世界可用校验、扣物品+回气血/内力/体力/施加状态），
            # 但不扣体力时间——judge 状态变更不自动连动大世界时钟，是否补体力/G打量时间 GM 另行在状态变更中补。
            item_name = c.get("物品") or c.get("名")
            if not item_name:
                results.append({"ok": False, "msg": "使用物品变更须传入 物品", "_结算错误": True})
                continue
            # 复用 go 私效果逻辑：调 _act_use_item 但显式跳过扣体力时间
            for r0 in _act_use_item(slot, explore, {"物品": item_name, "目标": c.get("目标"), "_judge_mode": True}):
                if not r0.get("ok"):
                    r0["_结算错误"] = True
                results.append(r0)
            continue
        elif kind == "写角色":
            # GM 落盘自创临时 NPC：传角色完整 dict，write_character 入 slot .data
            # （write_character 重名校验——与基线或本档已有角色同名即抛 ValueError，
            #  非法则本轮 judge 整件回滚；GM 应先用 wuxia_query 查询避重名）
            rec = c.get("角色")
            if not isinstance(rec, dict) or not rec.get("名称"):
                r = {"ok": False, "msg": "写角色变更须传入 角色（完整角色 dict，含名称）"}
            else:
                name = rec.get("名称")
                wuxue = rec.get("武学")
                has_wuxue = isinstance(wuxue, list) and any(
                    (isinstance(item, str) and item.strip())
                    or (isinstance(item, dict) and str(item.get("名称") or "").strip())
                    for item in wuxue
                )
                if not has_wuxue:
                    r = {"ok": False, "msg": f"写角色失败：角色【{name}】的武学不能为空"}
                else:
                    try:
                        dq.write_character(name, rec)
                        cur = explore.get("当前位置") or ""
                        if "·" in cur:
                            region = cur.split("·", 1)[0]
                            pos = explore.get("人物位置")
                            if not isinstance(pos, dict):
                                pos = {}
                            pos[name] = region
                            explore["人物位置"] = pos
                        r = {"ok": True, "msg": f"落盘角色【{name}】", "变更": f"落盘角色 {name}"}
                    except ValueError as e:
                        r = {"ok": False, "msg": f"写角色失败：{e}"}
            if not r.get("ok"):
                r["_结算错误"] = True
            results.append(r)
            continue
        elif kind in _FIELD_HANDLERS:
            r = _FIELD_HANDLERS[kind](slot, c)
        else:
            r = {"ok": False, "msg": f"未知状态变更类型【{kind}】"}
        if not r.get("ok"):
            r["_结算错误"] = True
        results.append(r)
    return results

def _act_config_equip(slot, explore, action):
    """配置装备：穿/脱。带 界面 直接渲染。无 操作/槽位 时视为打开界面（不修改）。"""
    op = action.get("操作")
    slot_pos = action.get("槽位")
    if not op or not slot_pos:
        return [{"ok": True, "msg": "打开装备界面"}]
    role = action.get("角色") or (sm.read_meta(slot) or {}).get("角色名")
    if op == "脱":
        return [_chg_equip(slot, {"类型": "装备", "操作": "脱", "角色": role, "槽位": slot_pos})]
    item = action.get("物品")
    if not item:
        return [{"ok": False, "msg": "穿装备须传入 物品"}]
    return [_chg_equip(slot, {"类型": "装备", "操作": "穿", "角色": role, "槽位": slot_pos, "名": item})]

def _act_character(slot, explore, action):
    """角色信息：查看角色完整信息（属性派生含武学+装备反哺）。带 界面 直接渲染。
    无 角色 参数 → message-ui 提示指定角色；带 角色 → character-ui。"""
    role = action.get("角色")
    if not role:
        return [{"ok": False, "msg": "查看角色信息须指定 角色"}]
    detail = _character_detail(slot, role)
    if detail is None:
        return [{"ok": False, "msg": f"未找到角色【{role}】"}]
    return [{"ok": True, "msg": f"查看角色信息 {role}", "角色": role, "角色信息": detail}]

def _act_wuxue_list(slot, explore, action):
    """武学列表：查看某角色已习得的全部武学（主动武学+心法分列）。带 界面 直接渲染。
    无 角色 参数 → message-ui 提示；带 角色 → wuxue-list-ui。"""
    role = action.get("角色")
    if not role:
        return [{"ok": False, "msg": "查看武学列表须指定 角色"}]
    char = _read_char(slot, role)
    if not char:
        return [{"ok": False, "msg": f"未找到角色【{role}】"}]
    return [{"ok": True, "msg": f"查看武学列表 {role}"}]

def _act_bag(slot, explore, action):
    """查看背包：返回 bag-ui，按 类型/子类型/适用场合 筛选主控物品栏。
    界面数据由 build_ui 经 _build_bag 构造。"""
    return [{"ok": True, "msg": "打开背包界面"}]

def _act_map(slot, explore, action):
    """查看地图：返回 map-ui，展示当前区域邻接图（当前场景向外的邻接链）+ 已知地点清单。
    界面数据由 build_ui 经 sc.build_map 构造（解析失败回退 message-ui 由 build_ui 兜底）。"""
    return [{"ok": True, "msg": "查看地图"}]

def _act_clue(slot, explore, action):
    """查看线索：返回 clue-ui，展示线索栏（进行中 / 已关闭）。
    界面数据由 build_ui 经 _build_clue_data 构造（读 explore.任务摘要及进度）。"""
    return [{"ok": True, "msg": "查看线索"}]

def _act_config_item(slot, explore, action):
    """配置物品（战斗携带物品种类）。带 界面 直接渲染（无修改字段时打开 item-ui）。
    无修改字段时视为打开界面（不修改）→ item-ui；
    带修改字段（操作 装/卸/换，或 携带物品 全量设）→ 执行并回写状态变更 → exploration-ui。"""
    role = action.get("角色") or (sm.read_meta(slot) or {}).get("角色名")
    if action.get("操作") in ("装", "卸", "换"):
        return [_carry_item_op(slot, role, action)]
    if "携带物品" in action:
        loadout = action.get("携带物品") or []
        return [_chg_carry_item(slot, {"类型": "携带物品", "操作": "设", "角色": role, "名列表": loadout})]
    return [{"ok": True, "msg": "打开道具界面"}]

def _act_config_wuxue(slot, explore, action):
    """配置武学（携带技能+运转心法）。带 界面 直接渲染。
    无修改字段时视为打开界面（不修改）→ wuxue-ui；
    带修改字段（操作 装/卸/换，或 携带技能 全量设，或 运转心法）→ 执行并回写状态变更 → exploration-ui。"""
    role = action.get("角色") or (sm.read_meta(slot) or {}).get("角色名")
    results = []
    if action.get("操作") in ("装", "卸", "换"):
        results.append(_carry_skill_op(slot, role, action))
    if "携带技能" in action:
        results.append(_chg_carry_skill(slot, {"类型": "携带技能", "操作": "设", "角色": role,
                                               "名列表": action.get("携带技能") or []}))
    if "运转心法" in action:
        xinfa = action.get("运转心法")
        results.append(_chg_xinfa(slot, {"类型": "运转心法", "操作": "设", "角色": role,
                                         "名": xinfa if xinfa != "无" else None}))
    return results or [{"ok": True, "msg": "打开武学界面"}]

def _act_other(slot, explore, action):
    """其他行为：琐碎不推进剧情的通用行为。行为类，扣体力+推进时间，返回 exploration-ui。"""
    return _apply_action_cost(slot, explore, action)

def _act_talk_observe(slot, explore, action):
    """交谈观察：与 NPC 交谈/调查/观察场景等推进剧情的探索行为。
    扣体力+推进时间（行为类）。剧情与数据后果统一由 GM 在 judge 一并落盘，
    交谈观察本身不携带状态变更。
    返回 exploration-ui（带更新后的时辰/体力/队伍状态），便于 GM 准确渲染。"""
    return _apply_action_cost(slot, explore, action)

def _act_attack(slot, explore, action):
    """攻击：玩家主动挑起的敌意/冲突意图（"打他XX""挑战XX"），可带 目标。
    扣体力+推进时间（行为类），仅结算行为成本；是否进入战斗由 GM 据场景判断，
    触发则于本轮 judge 传 战斗-触发/战斗-开始。go 隐藏界面，剧情与数据后果由 judge 承载。"""
    return _apply_action_cost(slot, explore, action)

def _act_start_game(slot, explore, action):
    """开始游戏：返回 title-ui 界面，含全部存档列表（slot 按最近存档降序，存档按时间戳降序）。
    若存档根目录不存在则创建、assets/data 缺失则解压 assets/data.zip（首次运行/迁移环境时初始化）。"""
    sm.ensure_dir()
    _ensure_data_dir()
    saves = sm.list_all_saves()
    return [{"ok": True, "msg": "开始游戏", "变更": "", "标题状态": "主页",
             "版本": sm.get_version(), "存档列表": saves,
             "next_slot": sm.next_slot_number()}]


def _act_title(slot, explore, action):
    """标题页无状态操作：草稿随 action 往返，不在 slot 0 落盘。"""
    sm.ensure_dir()
    _ensure_data_dir()
    return [handle_title_action(action)]

def _act_save_list(slot, explore, action):
    """存档列表：返回 save-ui 界面，含当前 slot 的存档列表（游戏内读档浏览/选择）。
    带 界面 直接渲染。仅列当前 slot（区别于开始游戏的全部 slot 列表）。"""
    saves = sm.list_slot_saves(slot)
    return [{"ok": True, "msg": "存档列表", "变更": "", "存档列表": saves}]

def _act_illegal(slot, explore, action):
    """非法指令：GM 判定玩家指令不合法或需补充信息时调用。不结算、不落盘、不推进时间，
    仅经 _build_response 返回 message-ui 提示。提示内容由 GM 写明于 action 的 提示 字段。"""
    return [{"ok": True, "msg": "非法指令", "变更": "",
             "提示": action.get("提示") or "指令不合法或信息不足，请重新输入。"}]

def _act_return_game(slot, explore, action):
    """返回游戏：从 explore.json 读当前状态，回放 exploration-ui。带 界面 直接渲染。
    玩家跨会话切入、或从子界面/读档后返回大世界游历时调此重渲染当前界面；数据全部取自磁盘
    explore.json（上回合 judge 落盘的 当前剧情/场景要素 原样回放至顶层 剧情描写/场景要素），
    队伍/位置/时辰/体力/相邻出口由 _build_state 派生。不修改任何状态。
    战斗进行中禁止：探测到该 slot 战斗临时文件即拒绝（玩家须先打完战斗）。"""
    if br.battle_exists(slot):
        return [{"ok": False, "msg": "当前有未结束的战斗，请先把战斗打完（使用战斗操控指令），不能返回游历"}]
    item = {"ok": True, "msg": "返回游戏", "变更": ""}
    plot = explore.get("当前剧情")
    if plot:
        item["当前剧情"] = plot
    elements = _norm_elements(explore.get("场景要素") or [])
    if elements:
        item["场景要素"] = elements
    return [item]

def _apply_narrative(slot, explore, text):
    """把精简后的累积剧情概括写入 explore.经历概括，每回合随 write_explore 落盘。
    经历概括为叙事定稿，不作为状态变更条目进结算数组；失败时返回错误条目供 settle 回滚。"""
    if not isinstance(text, str) or not text.strip():
        return [{"ok": False, "msg": "经历概括须为非空字符串", "_结算错误": True}]
    explore["经历概括"] = text
    return []

def _apply_clue(slot, explore, c):
    """单条线索更新：按名称 upsert 进 explore.任务摘要及进度（同名整体替换、否则新增）。
    状态变更条目 c：{类型:线索, 名称, 进展节点, 关闭(可选)}。
    注意：必须 upsert 而非 append——autosave 路径走 write_explore(preserve_narrative=False)
    整体覆盖、不经 merge 去重，append 会在该路径下留下同名重复条目。"""
    name = c.get("名称")
    if not name:
        return {"ok": False, "msg": "线索变更须传入 名称"}
    clue = {"名称": name}
    if c.get("进展节点") is not None:
        clue["进展节点"] = c.get("进展节点")
    if c.get("关闭") is not None:
        clue["关闭"] = c.get("关闭")
    clues = explore.get("任务摘要及进度") or []
    if not isinstance(clues, list):
        clues = []
    # 按名称 upsert：同名整体替换，否则新增
    idx = next((i for i, e in enumerate(clues) if isinstance(e, dict) and e.get("名称") == name), None)
    if idx is not None:
        clues = list(clues)
        clues[idx] = clue
    else:
        clues = list(clues) + [clue]
    explore["任务摘要及进度"] = clues
    return {"ok": True, "msg": f"线索 {name} 已更新", "变更": f"线索 {name} 已更新"}

def _act_create_slot(slot, explore, action):
    """在指定空闲 slot 建档；支持完整角色或 title-ui 紧凑创建草稿。"""
    char = action.get("角色")
    if char is None and action.get("创建草稿") is not None:
        char, error = build_character(action.get("创建草稿"), action.get("初始武学"))
        if error:
            return [{"ok": False, "msg": error}]
    if not isinstance(char, dict) or not char.get("名称"):
        return [{"ok": False, "msg": "创建角色须传入 角色（完整角色 dict，含名称），或 创建草稿+初始武学"}]
    if not sm._slot_writable(slot):
        next_slot = sm.next_slot_number()
        return [{"ok": False,
                 "msg": f"创建角色必须传入正整数槽位，最新可用槽位为 {next_slot}",
                 "错误码": "create_slot_required", "next_slot": next_slot}]
    try:
        r = sm.create_slot(char, slot)
    except sm.SlotOccupiedError as exc:
        return [{"ok": False, "msg": str(exc), "错误码": exc.code,
                 "next_slot": exc.next_slot}]
    new_slot = r.get("slot")
    # 落点补场景后缀：create_slot 的落点是纯区域名（read_explore 已修正为 map 节点名），
    # 此处落该区域驿站出口场景，写回新 slot 的 explore.json，使开局相邻出口可用
    region = (es.get(new_slot, "当前位置") or r.get("当前位置") or "").split("·")[0]
    station = (sc.load_scenes().get("驿站出口", {}) or {}).get(region)
    if station:
        new_pos = f"{region}·{station}"
        es.set(new_slot, "当前位置", new_pos, narrative=True)
        r["当前位置"] = new_pos
    # 不在此存首档：建号后 GM 调 judge 写开场白时统一存档（存档后 rnd 才+1），首档即含开场白
    results = [{"ok": True, "msg": f"已创建角色 slot {new_slot} {char['名称']}",
                "变更": "角色已创建", "新建slot": new_slot,
                "落点": r.get("当前位置"),
                "当前时间": r.get("当前时间"), "剩余": r.get("剩余")}]
    # 附配发明细变更行（替代原初入江湖的 starter 提示），渲染在 judge 的结算栏
    results += _starter_changes(char)
    return results

def _starter_changes(char):
    """据落盘后的角色 dict 生成初始配发的 变更 条目（每条一行，供结算栏逐条高亮渲染）。
    装备按 武器1/武器2/护甲/饰品/冠巾 顺序取非空项；武学取「武学」list 各名称。"""
    changes = []
    equip = char.get("装备") or {}
    for slot_name in ("武器1", "武器2", "护甲", "饰品", "冠巾"):
        eq = equip.get(slot_name)
        if eq:
            changes.append({"ok": True, "变更": f"获得 {eq}"})
    changes.append({"ok": True, "变更": "获得 铜钱500"})
    for name, count in (("小还丹", 2), ("补气丸", 2)):
        changes.append({"ok": True, "变更": f"获得 {name}×{count}"})
    for w in char.get("武学") or []:
        if isinstance(w, dict) and w.get("名称"):
            changes.append({"ok": True, "变更": f"学会 {w['名称']}"})
        elif isinstance(w, str) and w:
            changes.append({"ok": True, "变更": f"学会 {w}"})
    return changes

def _act_save(slot, explore, action):
    """存档：调 save_manager.save 写一份存档。标签由 action.标签 传入（必填，GM 据进度概括）。
    可选 经历概括：手动存档时一并固化经历概括（仅存档落盘）。带 界面 直接渲染。

    手动存档的 当前剧情/场景要素 取磁盘 explore.json 现值（上回合 judge 落盘的），
    而非事务内存 explore——保存游戏本身不推进剧情，应快照当前已落盘的剧情/场景状态。"""
    label = action.get("标签")
    if not label or not str(label).strip():
        return [{"ok": False, "msg": "保存游戏须传入 标签（存档名），不得为空"}]
    label = str(label).strip()
    if action.get("经历概括") is not None:
        results = _apply_narrative(slot, explore, action.get("经历概括"))
        if results:  # 经历概括非法 → 直接返回错误，不存档
            return results
    else:
        results = []
    # 手动存档：当前剧情/场景要素 取磁盘 explore.json 现值（覆盖事务内存态，避免依赖本轮内存）
    disk = es.get_all(slot)
    state = dict(explore)
    if "当前剧情" in disk:
        state["当前剧情"] = disk["当前剧情"]
    if "场景要素" in disk:
        state["场景要素"] = _norm_elements(disk["场景要素"]) or []
    path = sm.save(state, slot, label=label)
    fname = os.path.basename(path) if path else ""
    results.append({"ok": True, "msg": f"已保存游戏 {label}".strip(),
                    "变更": f"保存游戏 {label}"})
    # 渲染数据从磁盘 explore.json 现值读取：剧情/要素挂入结算条目，
    # 经 _inject_narrative 注入返回顶层，供默认 exploration-ui 路由渲染（不跳界面）
    if disk.get("当前剧情"):
        results[-1]["当前剧情"] = disk["当前剧情"]
    _els = _norm_elements(disk.get("场景要素") or [])
    if _els:
        results[-1]["场景要素"] = _els
    return results

def _act_restore(slot, explore, action):
    """读档：调 save_manager.restore 恢复指定存档。目标由 action.目标 传入
    （File_N/时间戳/label/子串）。带 界面 直接渲染。restore 会重写 slot 的 .data/ 与 explore.json。"""
    target = action.get("目标")
    if not target:
        return [{"ok": False, "msg": "加载存档须传入 目标（File_N/时间戳/label/子串）"}]
    state = sm.restore(slot, target)
    # 旧档落点可能无场景后缀（相邻出口为空）：补该区域驿站出口场景，使读档后出口可用
    pos = state.get("当前位置") or ""
    if pos and "·" not in pos:
        station = (sc.load_scenes().get("驿站出口", {}) or {}).get(pos)
        if station:
            new_pos = f"{pos}·{station}"
            es.set(slot, "当前位置", new_pos, narrative=True)
            state["当前位置"] = new_pos
    # 读档覆盖世界状态：任何残留的战斗中临时文件作废，清理以免「返回游戏」误判
    _clear_battle_tmp(slot)
    # 读档即重置判定留痕：清空 check.json，避免旧轮次判定记录串入新存档
    try:
        os.remove(os.path.join(sm.slot_path(slot), "check.json"))
    except OSError:
        pass
    out = {"ok": True, "msg": f"已加载存档 {target}。建议下一轮推演开始前重新读取 wuxia-rpg-worldview.md 与该地区 wuxia-rpg-storylines.md，避免设定冲突",
           "变更": "存档已加载", "剩余": state.get("剩余")}
    # 读档即回顾：经历概括与线索栏随返回顶层透出（GM 续写剧情据此，不再单独调 event summary）
    out["经历概括"] = state.get("经历概括")
    out["线索栏"] = state.get("任务摘要及进度")
    # 渲染数据从存档读取：剧情/要素挂入结算条目，经 _inject_narrative 注入顶层，
    # exploration-ui 即完整渲染（读档后无需再调 返回游戏 回放）
    if state.get("当前剧情"):
        out["当前剧情"] = state["当前剧情"]
    _els = _norm_elements(state.get("场景要素") or [])
    if _els:
        out["场景要素"] = _els
    return [out]

def _act_delete(slot, explore, action):
    """删除存档：目标缺省→删整个角色 slot；传目标→删该 slot 内单个存档点。
    目标 slot 由 action.槽位 指定，缺省取当前 slot。带 界面 直接渲染。
    返回刷新后的全部存档列表，供 _build_response 渲染 title-ui。"""
    target = action.get("目标")
    try:
        target_slot = int(action["槽位"]) if action.get("槽位") is not None else slot
    except (TypeError, ValueError):
        return [{"ok": False, "msg": "槽位须为整数 slot 编号"}]
    if target:
        try:
            remaining = sm.delete_save(target_slot, str(target))
        except FileNotFoundError as e:
            return [{"ok": False, "msg": str(e)}]
        return [{"ok": True, "msg": f"已删除 slot {target_slot} 存档 {target}（剩余{remaining}个）",
                 "槽位": target_slot,
                 "存档列表": sm.list_all_saves()}]
    sm.delete_slot(target_slot)
    return [{"ok": True, "msg": f"已删除角色档 slot {target_slot}",
             "槽位": target_slot,
             "存档列表": sm.list_all_saves()}]

_ACTION_HANDLERS = {
    "休息": _act_rest,
    "远行（徒步）": _act_travel,
    "远行（舟车）": _act_travel,
    "使用物品": _act_use_item,
    "购买": _act_buy,
    "出售": _act_sell,
    "赠与物品": _act_gift,
    "战斗-处决": _act_battle_execute,
    "战斗-使用武学": _act_battle_skill,
    "战斗-使用物品": _act_battle_item,
    "战斗-休息": _act_battle_rest,
    "战斗-逃跑": _act_battle_flee,
    "战斗-认输": _act_battle_surrender,
    "遣散": _act_dismiss,
    "武学精进": _act_mastery,
    "配置装备": _act_config_equip,
    "配置物品": _act_config_item,
    "配置武学": _act_config_wuxue,
    "创建角色": _act_create_slot,
    "保存游戏": _act_save,
    "加载存档": _act_restore,
    "删除存档": _act_delete,
    "其他行为": _act_other,
    "交谈观察": _act_talk_observe,
    "攻击": _act_attack,
    "角色信息": _act_character,
    "查看背包": _act_bag,
    "武学列表": _act_wuxue_list,
    "查看地图": _act_map,
    "查看线索": _act_clue,
    "开始游戏": _act_start_game,
    "标题-操作": _act_title,
    "存档列表": _act_save_list,
    "非法指令": _act_illegal,
    "返回游戏": _act_return_game,
}

