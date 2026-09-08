#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大世界游历统一结算前端——go/judge 两步式。

- **engine go**：玩家主动指令的机制结算（休息/远行/使用物品/购买/出售/遣散/武学精进/
  战斗操控/配置/查询/存档等）。落盘机制后果，**不增轮次、不自动存档**。**返回带 `界面`
  则按对应渲染文档直接渲染**；以下情形**隐藏 `界面`、GM 据「无界面→调 judge」下调
  engine judge：休息/远行（徒步）/远行（舟车）/交谈观察/其他行为，或战斗操控且战斗结束
  那一回合。普通配置/查询/存档类带 `界面` 直接渲染。
- **engine judge**：GM 基于 go 的既成结果推演后的裁定落盘。行为数组平铺一等状态变更
  条目（无剧情推动包壳）+ 顶层叙事字段（当前剧情必填/场景要素/经历概括）。任一状态
  变更非法则整体回滚本轮 judge，go 已落盘的机制后果不受影响。**仅返回
  exploration-ui 的 judge 结算成功才推进交互轮次**（与传入状态变更内容无关）并可能
  自动存档；战斗-开始/战斗-触发 为 judge 专属 action（推演产物，产出 battle-ui /
  exploration-battle-ui），结算成功但**不推进轮次**。
- **存档判定**：轮次仅由返回 exploration-ui 的 judge 推进；轮次%周期==0 时
  save_manager.save 自动存档。
- **状态镜像**：写 explore.json（持久状态 + 叙事，经历概括由 judge 顶层入参覆盖、未传则保留）。
- **分工边界**：battle.py 战后已自落盘气血/内力/物品消耗；经验/处决/战利品由 GM 经
  judge 状态变更落盘。战斗中途禁止 返回游戏（须先打完）。
- **go/judge 状态一致性**：go 落盘后至 judge 调用之间，不得绕过 engine 直接改角色文件。

CLI（均从 stdin 读取 JSON）：
  python3 scripts/engine.py go
  python3 scripts/engine.py judge
  python3 scripts/engine.py check
  python3 scripts/engine.py random-event
  python3 scripts/engine.py query
  python3 scripts/engine.py setting
  python3 scripts/engine.py recommend
  python3 scripts/engine.py map-query
"""
import os, sys
import json
from common import dao as dq
from common.json_io import JsonReadError
from store import save_manager as sm
from world import scene as sc
from settle import engine_state as est

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from settle.engine_io import _battle_last_path, _clear_battle_tmp, _set_slot, _sync_party
from settle.engine_ui import _build_response, _gm_autosave_hint, _inject_narrative, _norm_elements, _region_info, build_ui
from settle.engine_actions import _ACTION_HANDLERS, _act_battle, _act_battle_advance, _act_battle_trigger, _apply_changes, _apply_narrative, _maybe_battle_end_ui
from store.tips import write_tips as _write_tips, read_tips as _read_tips
from store.battle_last import write_battle_last as _write_battle_last, battle_last_path as _battle_last_path
from store.check_log import missing_check_hints as _missing_check_hints, append_check as _append_check
from common import check as _check
from common import dao as _dq
from world import map_query as _map_query

# 功能场景类型 → 该功能NPC须支持的特殊指令（go 行为名）
_SCENE_TYPE_COMMANDS = {
    "驿站": ["远行（舟车）"],
    "店铺": ["购买", "出售"],
    "客栈": ["投宿"],
}

# action 分发表
# 扣体力/时间集合（仅体力兜底与计费判定用，与「是否需 judge 推演」无关）
_STAMINA_COST_ACTIONS = {"攻击", "休息", "远行（徒步）", "远行（舟车）", "使用物品", "购买", "出售", "遣散", "交谈观察", "其他行为", "赠与物品"}

# 是否需 GM 下调 judge 推演，由 _build_response 返回的 界面 字段决定（无界面=交 GM），
# 不再按 action 类型集合判定（避免打开界面/结算同类型被误伤）。
# judge 专属 action（推演产物，产出战斗界面）：不接受于 go
_JUDGE_ACTIONS = {"战斗-开始", "战斗-触发", "战斗-推进"}

# 门厅哨兵槽位（slot<=0，前端未选存档）允许的动作：不依赖真 slot、不向 slot_0 落盘。
# 其余动作在哨兵槽位上一律拒绝，杜绝 slot 0 误落盘产生垃圾存档。
_LOBBY_SLOT0_ACTIONS = {"创建角色", "开始游戏", "删除存档"}

_CONFIG_ACTIONS = {"配置装备", "配置物品", "配置武学", "武学精进",
                   "创建角色", "保存游戏", "加载存档", "删除存档", "开始游戏", "存档列表", "角色信息", "查看背包", "武学列表",
                   "查看地图", "查看线索",
                   "战斗-使用武学", "战斗-使用物品", "战斗-休息", "战斗-逃跑", "战斗-认输", "战斗-处决",
                   "非法指令",
                   "返回游戏"}


def _settle_go(slot, actions=None):
    """engine go：玩家主动指令的机制结算。落盘机制后果（角色/explore 体力/时间/位置/队伍），
    不推进世界轮次、不触发自动存档（轮次仅由 judge 推进）。
    返回带 `界面` 字段——GM 据此直接读对应渲染文档；以下情形**隐藏 `界面`**（休息/远行（徒步）/
    远行（舟车）/交谈观察/其他行为，或战斗操控且战斗结束那一回合），GM 据「无界面→调 judge」下调 engine judge
    （judge 始终保留 `界面`）。"""
    _set_slot(slot)
    if isinstance(actions, dict):
        actions = [actions]
    actions = actions or []

    # 哨兵槽位 slot<=0（门厅未选存档）：仅放行不依赖真 slot 的门厅动作，
    # 其余一律拒绝，杜绝 slot 0 落盘产生垃圾 slot_0 存档
    if not sm._slot_writable(slot):
        req = {a.get("类型") for a in actions if isinstance(a, dict)}
        bad = req - _LOBBY_SLOT0_ACTIONS
        if bad:
            return _build_response(slot, [], False, 0, [],
                                   error=f"未选定存档（槽位 {slot}），仅可执行门厅操作；不支持的指令：{('、'.join(sorted(bad)))}")

    valid = []
    for a in actions:
        if not isinstance(a, dict):
            return _build_response(slot, valid, False, sm.rounds_until_save(slot), [],
                                   error="存在非对象 action")
        t = a.get("类型")
        if t in _JUDGE_ACTIONS:
            return _build_response(slot, valid, False, sm.rounds_until_save(slot), [],
                                   error=f"【{t}】属剧情推演产物，须经 engine judge 触发，不走 go")
        if t not in _ACTION_HANDLERS:
            return _build_response(slot, valid, False, sm.rounds_until_save(slot), [],
                                   error=f"未知 action 类型【{t}】")
        valid.append(a)

    # 持久状态载体：从 explore.json 读，handler 直接改它，最后统一落盘
    explore = sm.read_explore(slot) or {}

    # 体力兜底（仅扣体力的行为类）。
    if any(a.get("类型") in _STAMINA_COST_ACTIONS for a in valid):
        refill = {"休息", "远行（舟车）"}
        if not any(a.get("类型") in refill for a in valid):
            if not int(explore.get("体力", 0) or 0):
                return _build_response(slot, valid, False, sm.rounds_until_save(slot), [],
                                       error="体力不支，无法行动，需休息恢复")

    # 事务态：所有角色改动先暂存内存，全过才统一刷盘；任一失败整体回滚，不落盘
    est._TXN = {}
    est._SCENE_STAGED = {}
    est._SCENE_TYPE_STAGED = {}
    results = []
    bt_data = None  # 战斗操控 action 的 battle-ui 数据
    party_changes = []  # 本轮在队变更（成功者），用于同步 explore.队伍
    try:
        all_ok = True
        for a in valid:
            t = a.get("类型")
            handler = _ACTION_HANDLERS[t]
            rs = handler(slot, explore, a)
            # 战斗 action 返回 (results, bt_data) 元组：results 并入结算，bt_data 为 battle-ui 数据
            if isinstance(rs, tuple):
                step_results, bt_data = rs
                rs = step_results
            if not isinstance(rs, list):
                rs = [rs]
            for r in rs:
                results.append(r)
                if not r.get("ok"):
                    all_ok = False
                if r.get("ok") and r.get("_在队变更"):
                    party_changes.append(r["_在队变更"])
        if not all_ok:
            # 玩家输入错误（go 均为玩家指令，无 GM 结算错误概念），整体回滚不落盘
            failed = [r for r in results if not r.get("ok")]
            err_msgs = [r["msg"] for r in failed]
            results = [{k: v for k, v in r.items() if not str(k).startswith("_")} for r in results]
            est._TXN = None
            return _build_response(slot, valid, False, sm.rounds_until_save(slot), results,
                                   error="操作失败：" + "；".join(err_msgs))
        results = [{k: v for k, v in r.items() if not str(k).startswith("_")} for r in results]
        # 全部通过 → 提交：暂存的角色改动一次性刷盘，场景登记合并落盘
        for name, char in est._TXN.items():
            dq.update_char(name, char)
        sc.commit_staged(slot, est._SCENE_STAGED, est._SCENE_TYPE_STAGED)
        est._TXN = None
        est._SCENE_STAGED = None
        est._SCENE_TYPE_STAGED = None
    finally:
        est._TXN = None
        est._SCENE_STAGED = None
        est._SCENE_TYPE_STAGED = None

    if party_changes:
        _sync_party(slot, explore, party_changes)

    # 推进世界判定：玩家主动行为类，或战斗操控且本轮战斗结束
    # 战斗操控：落盘 explore + 缓存战斗底稿（battle_last.json）；go 一律无界面，
    # GM 润色 战报 后以 judge 战斗-推进 出 battle-ui（每回合 go/judge 两步式）
    if bt_data is not None:
        sm.write_explore(slot, explore, preserve_narrative=True)
        status = (bt_data.get("战局状态") or {}).get("状态")
        if status and status != "进行中":
            bt_data.update(_region_info(slot, explore))  # 战后处置判定路线参考
        # go 默认无界面（推进 judge 出 battle-ui）；终局我方胜时直接出 battle-end-ui（处决裁定界面）
        bt_data.pop("界面", None)
        _write_battle_last(slot, bt_data)
        _maybe_battle_end_ui(bt_data)
        bt_data["saved"] = False
        bt_data["剩余"] = sm.rounds_until_save(slot)
        bt_data["结算"] = results
        bt_data["槽位"] = slot
        _inject_narrative(bt_data, results)
        # go 机制后果提示落盘（覆盖写）：judge 接下时拼到结算最前，消费一次
        _write_tips(slot, results)
        return bt_data

    # 存档/建档/读档 handler 内部已重写 explore.json，不再覆盖
    save_related = {"创建角色", "保存游戏", "加载存档", "删除存档"}
    # 纯只读/查询动作（不改 explore）：回写会凭空刷新 mtime、甚至给未建档 slot
    # 写出空 explore.json 造垃圾目录，故一律跳过回写。
    read_only = {"开始游戏", "存档列表", "返回游戏", "角色信息", "查看背包",
                 "武学列表", "查看地图", "查看线索", "非法指令"}
    types = {a.get("类型") for a in valid}
    if (explore
            and not (types & save_related)
            and not (types <= read_only)):
        sm.write_explore(slot, explore, preserve_narrative=True)

    # 建档时 stdin 槽位≠新档：剩余/tips/区域场景均须按新 slot 取（其余动作 state_slot==slot 无感）
    state_slot = slot
    for r in results:
        if r.get("新建slot"):
            state_slot = r["新建slot"]
            break
    resp = _build_response(slot, valid, False, sm.rounds_until_save(state_slot), results)
    # 无界面 → 需 GM 推演：补区域场景图供 GM 设计路线/移动；GM 据此下调 judge。
    # 有界面（子界面/弹窗/exploration-ui）→ 前端直接渲染，不补区域场景图。
    if resp.get("界面") is None:
        slot_explore = sm.read_explore(state_slot) or {} if state_slot != slot else explore
        resp.update(_region_info(state_slot, slot_explore))
        # 推演前强制判定思考提示：GM 下调 judge 前必先回溯本回合是否该判
        resp["GM提示"] = "推演剧情前先自问：本回合剧情发展是否依赖角色某项技艺/属性水平高低？涉及即先调 wuxia_check（不可用时 engine check）掷骰，并据结果推演。"
    # go 机制后果提示落盘（覆盖写）：judge 接下时拼到结算最前，消费一次
    _write_tips(state_slot, results)
    return resp

def _settle_judge(slot, changes=None, narrative=None):
    """engine judge：GM 基于 go 的既成状态（go 已落盘机制后果）推演后，裁定落盘。

    changes：行为数组，元素为两类——
      · 状态变更条目（{类型:铜钱/经验/关系度/物品/装备/在队/气血/内力/死亡/时间/抵达/
        登记场景/线索/武学/体力/战斗-结束...}），经 _apply_changes 裁定
        （战斗-结束：战斗整场耗时耗力——体力-20/时间+8刻，自动结算，战后处置必带）；
      · 独立 action 条目（战斗-开始/战斗-触发），单独 dispatch 产出 battle-ui。
    narrative：顶层叙事字段 {当前剧情(必填)/场景要素/经历概括}。
    任一状态变更非法 → 整体回滚本轮 judge（不落盘），go 已落盘的机制后果不受影响。
    仅返回 exploration-ui 的结算成功才推进交互轮次并可能自动存档（与状态变更内容无关）；
    返回 battle-ui / exploration-battle-ui 的结算成功不推进轮次、不自动存档。
    """
    _set_slot(slot)
    narrative = narrative or {}
    if isinstance(changes, dict):
        changes = [changes]
    changes = changes or []

    # 哨兵槽位 slot<=0（门厅未选存档）：judge 永远不该在门厅执行
    if not sm._slot_writable(slot):
        return _build_response(slot, [], False, 0, [],
                               error=f"未选定存档（槽位 {slot}），judge 不可在门厅执行")
    explore = sm.read_explore(slot) or {}

    # 顶层叙事校验：当前剧情必填；场景要素须为 {主体, 描写} 对象数组
    plot = narrative.get("当前剧情")
    has_battle_entry = any(isinstance(c, dict) and c.get("类型") in _JUDGE_ACTIONS for c in changes)
    if not has_battle_entry and (not plot or not str(plot).strip()):
        return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                               error="judge 缺 `当前剧情`（本回合拟展示给玩家的剧情描写，必填，不可为空；战斗类 judge 可填空）",
                               gm_error=True)
    elements = narrative.get("场景要素")
    if elements is not None:
        elements = _norm_elements(elements)
        if elements is None:
            return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                   error="judge `场景要素` 须为 {主体, 描写} 对象数组（主体必填）",
                                   gm_error=True)

    # 判定留痕核对（应判尽判红线）：非战斗 judge 且有剧情文本时，核对本轮 check.json
    # 记录的判定提示是否都已嵌入剧情文本；缺失=GM 掷骰却未在叙事带出，须回退补上。
    # 战斗推进轮跳过（剧情可空、不增轮次，记录留待战后处置 exploration-ui judge 核对）
    if not has_battle_entry and plot and str(plot).strip():
        missing = _missing_check_hints(slot, plot)
        if missing:
            return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                   error=f"判定提示未带入剧情：本轮已掷骰但剧情文本缺少 {missing}，"
                                        f"须将判定结果提示反引号高亮后嵌入叙事（不得遗漏掷骰结果）",
                                   gm_error=True)

    # 拆行为数组：独立战斗 action 条目 vs 状态变更条目
    battle_entries = []
    change_entries = []
    for c in changes:
        if not isinstance(c, dict):
            return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                   error="judge 存在非对象条目", gm_error=True)
        t = c.get("类型")
        if t in _JUDGE_ACTIONS:
            battle_entries.append(c)
        else:
            change_entries.append(c)

    # go 的机制后果提示在前：judge 每回合读 tips.json（成功消费后清空，失败保留重调），
    # 把 go 的变更行拼到本次 结算 最前。文件由 go 单方覆盖更新（有则写入、无则空数组）。
    tips = _read_tips(slot)
    # 事务态：judge 整体回滚
    est._TXN = {}
    est._SCENE_STAGED = {}
    est._SCENE_TYPE_STAGED = {}
    results = []
    bt_data = None
    party_changes = []
    try:
        # 战斗 action 条目：调 battle.py 产出 battle-ui（战斗-开始 run_init / 战斗-触发 选择界面）
        for c in battle_entries:
            t = c.get("类型")
            if t == "战斗-开始":
                rs = _act_battle(slot, explore, c)
            elif t == "战斗-推进":
                rs = _act_battle_advance(slot, explore, c)
            else:
                rs = _act_battle_trigger(slot, explore, c)
            if isinstance(rs, tuple):
                step_results, bt_data = rs
                rs = step_results
            if not isinstance(rs, list):
                rs = [rs]
            for r in rs:
                r.setdefault("_结算错误", True)
                results.append(r)

        # 状态变更条目；成功且在队变更需记，用于同步 explore.队伍
        for r in _apply_changes(slot, explore, change_entries):
            results.append(r)
            if r.get("ok") and r.get("_在队变更"):
                party_changes.append(r["_在队变更"])

        # 经历概括（叙事定稿；失败打 _结算错误）
        if narrative.get("经历概括") is not None:
            results += _apply_narrative(slot, explore, narrative.get("经历概括"))

        all_ok = all(r.get("ok") for r in results)
        if not all_ok:
            failed = [r for r in results if not r.get("ok")]
            err_msgs = [r["msg"] for r in failed]
            results = [{k: v for k, v in r.items() if not str(k).startswith("_")} for r in results]
            est._TXN = None
            return _build_response(slot, [], False, sm.rounds_until_save(slot), results,
                                   error="judge 状态变更结算异常：" + "；".join(err_msgs),
                                   gm_error=True)

        # 红线（功能NPC必露脸+特殊指令）：状态变更落盘后，当前场景若为功能场景，场景要素必含
        # 该功能NPC一条，且该要素须带对应特殊指令（驿站→远行（舟车），店铺→购买/出售，客栈→休息）。
        # 校验置于变更应用之后，使 抵达/远行 改变位置后的新场景亦受约束。
        if elements:
            cur_pos = explore.get("当前位置") or ""
            cur_region, _, cur_scene = cur_pos.partition("·")
            stype = sc.scene_type(slot, cur_region, cur_scene)
            npc = sc.scene_npc(slot, cur_region, cur_scene)
            req_cmds = _SCENE_TYPE_COMMANDS.get(stype) if stype else None
            if npc and req_cmds:
                npc_el = next((e for e in elements if e.get("主体") == npc), None)
                if not npc_el:
                    est._TXN = None
                    return _build_response(slot, [], False, sm.rounds_until_save(slot), results,
                                           error=f"当前场景【{cur_scene}】为功能场景，`场景要素` 必含一条以功能NPC【{npc}】为主体的要素",
                                           gm_error=True)
                have = set(c.get("名称") for c in (npc_el.get("特殊指令") or []) if isinstance(c, dict))
                missing = [c for c in req_cmds if c not in have]
                if missing:
                    est._TXN = None
                    return _build_response(slot, [], False, sm.rounds_until_save(slot), results,
                                           error=f"功能NPC【{npc}】的要素须带特殊指令 {req_cmds}（缺少 {missing}）",
                                           gm_error=True)

        # 全过 → 叙事落 explore + 角色改动/场景登记统一落盘
        if plot and str(plot).strip():  # 战斗类 judge 允许空剧情（战斗推进无探索叙事），空则不覆盖
            explore["当前剧情"] = plot
        if elements is not None:
            explore["场景要素"] = elements
        results = [{k: v for k, v in r.items() if not str(k).startswith("_")} for r in results]
        for name, char in est._TXN.items():
            dq.update_char(name, char)
        sc.commit_staged(slot, est._SCENE_STAGED, est._SCENE_TYPE_STAGED)
        est._TXN = None
        est._SCENE_STAGED = None
        est._SCENE_TYPE_STAGED = None
    finally:
        est._TXN = None
        est._SCENE_STAGED = None
        est._SCENE_TYPE_STAGED = None

    if party_changes:
        _sync_party(slot, explore, party_changes)

    # go 的机制后果提示拼到结算最前：go 写入 tips.json 的变更行在 judge 返回中先呈现
    if tips:
        results = [{"ok": True, "变更": line} for line in tips] + results
        # 消费一次：成功 judge 清空 tips（失败路径在更早已 return，原样保留供重调），
        # 避免多连发 judge（如 战斗-触发→战斗-开始→战后处置）重复打印同一批 go 变更行
        _write_tips(slot, [])

    # 战斗 action 产出 battle-ui / exploration-battle-ui：结算成功但不推进交互轮次、
    # 不自动存档（轮次仅由返回 exploration-ui 的 judge 推进），仅落盘叙事/状态
    if bt_data is not None:
        sm.write_explore(slot, explore, preserve_narrative=True)
        bt_data.setdefault("界面", "battle-ui")
        _maybe_battle_end_ui(bt_data)  # AI自动整场：终局我方胜也出 battle-end-ui（带处决候选）
        bt_data["saved"] = False
        bt_data["剩余"] = sm.rounds_until_save(slot)
        bt_data["结算"] = results
        bt_data["槽位"] = slot
        if plot and str(plot).strip():
            bt_data["剧情描写"] = plot
        if elements:
            bt_data["场景要素"] = elements
        # 战斗-开始/触发 开启战斗 → 清理旧战斗临时文件前置也由 run_init 覆盖，无需此处处理
        bt_data["渲染模式"] = os.environ.get("WUXIA_RPG_RENDER_MODULE", "")
        return bt_data

    # 以下仅 exploration-ui 路径：judge 结算成功即推进交互轮次（每 CHECKPOINT_PERIOD
    # 轮触发自动存档），与状态变更内容无关
    saved = False
    # 先判存档（用当前 rnd）→ rnd+1 落盘 → 再存档（存档内 round=+1 后的值）。
    # 这样读档恢复的是已推进的 round，下一轮不会因 round%周期==0 重复触发存档。
    rnd = sm.read_round(slot)
    will_save = (rnd % sm.CHECKPOINT_PERIOD == 0)
    sm.write_round(slot, rnd + 1)
    if will_save:
        # rnd=0 即建号首回合，首档标 label=初入江湖；其余自动存档标 自动存档
        sm.save(explore, slot, label=("初入江湖" if rnd == 0 else "自动存档"))
        saved = True
        results.append({"ok": True, "变更": "自动存档完成"})
    else:
        sm.write_explore(slot, explore, preserve_narrative=True)

    # 只在触发自动存档时附加全量经历概括+线索栏，供 GM 周期性回顾剧情（否则不带，冗余大）

    # 战后处置落盘完成：清理该 slot 的战斗临时文件（避免「返回游戏」误判战斗中）
    _clear_battle_tmp(slot)

    # exploration-ui：拼公共字段 + build_ui 取状态与叙事（narrative 已落 explore.json）
    base = {"saved": saved, "剩余": sm.rounds_until_save(slot), "结算": results, "槽位": slot}
    if saved:
        base["GM参考"] = _gm_autosave_hint(slot)
    ctx = {"explore": explore, "narrative": {"当前剧情": plot, "场景要素": elements},
           "results": results, "with_summary": saved}
    base.update(build_ui(slot, "exploration-ui", ctx))
    if "界面" in base:
        base["渲染模式"] = os.environ.get("WUXIA_RPG_RENDER_MODULE", "")
    return base

def go(slot, actions=None):
    """engine go 入口：玩家主动指令的机制结算（不接 render 渲染层）。"""
    return _settle_go(slot, actions)

def judge(slot, payload=None):
    """engine judge 入口：GM 推演后的裁定落盘。
    payload: {"槽位":N(由调用方剥离), "行为":[...], "当前剧情":..., "场景要素":[...], "经历概括":...}
    顶层仅允许 行为/当前剧情/场景要素/经历概括 四字段；其余（如把线索/状态变更误放顶层）
    一律报错，避免静默忽略。"""
    payload = payload or {}
    _ALLOWED_TOP = {"槽位", "行为", "当前剧情", "场景要素", "经历概括"}
    extra = set(payload.keys()) - _ALLOWED_TOP
    if extra:
        return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                               error=f"judge 顶层出现非预期字段：{('、'.join(sorted(extra)))}。"
                                     f"仅允许 行为/当前剧情/场景要素/经历概括；"
                                     f"状态变更（如线索）须放「行为」数组内",
                               gm_error=True)
    narrative = {k: payload[k] for k in ("当前剧情", "场景要素", "经历概括") if k in payload}
    return _settle_judge(slot, payload.get("行为"), narrative)


def check(payload=None):
    """属性/技艺判定；有效结果写入当前轮判定留痕。"""
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        return {"错误": "check stdin 须为 JSON 对象"}
    slot = payload.get("槽位")
    if slot is None:
        return {"错误": "check 缺少 槽位"}
    _dq.set_slot(slot)
    attrs = payload.get("属性") or []
    judge_names = payload.get("判定角色") or []
    opponent = payload.get("对抗") or ""
    base_rate = payload.get("基础成功率", 50)
    if isinstance(attrs, str):
        attrs = [a.strip() for a in attrs.split(",") if a.strip()]
    if isinstance(judge_names, str):
        judge_names = [n.strip() for n in judge_names.split(",") if n.strip()]
    result = _check.run_check(attrs, judge_names, opponent, base_rate)
    if "结果" in result:
        rnd = sm.read_round(slot)
        _append_check(slot, {
            "轮次": rnd,
            "属性": attrs,
            "判定角色": judge_names,
            "对抗": opponent,
            "基础成功率": base_rate,
            "结果": result["结果"],
            "提示": result.get("提示", ""),
        })
    return result


def random_event(payload=None):
    """随机事件判定；切换槽位但不写判定留痕。"""
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        return {"错误": "random-event stdin 须为 JSON 对象"}
    slot = payload.get("槽位")
    if slot is None:
        return {"错误": "random-event 缺少 槽位"}
    _dq.set_slot(slot)
    return _check.run_random_event(payload.get("基础成功率", 15))


def _prepare_query(payload, command, allowed):
    """校验只读查询公共顶层参数并切换 DAO slot；返回错误对象或 None。"""
    if not isinstance(payload, dict):
        return {"错误": f"{command} stdin 须为 JSON 对象"}
    extra = set(payload) - set(allowed)
    if extra:
        return {"错误": f"{command} 出现非预期字段：{'、'.join(sorted(extra))}"}
    slot = payload.get("槽位")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
        return {"错误": f"{command} 缺少有效 槽位（未建档时传 0）"}
    try:
        _dq.set_slot(slot)
    except (TypeError, ValueError) as exc:
        return {"错误": f"{command} 槽位无效：{exc}"}
    return None


def query(payload=None):
    """基础数据查询：类型/名称/派生/字段/等级/位置，返回结构化 JSON。"""
    payload = {} if payload is None else payload
    error = _prepare_query(payload, "query", {"槽位", "类型", "名称", "派生", "字段", "等级", "位置"})
    if error:
        return error
    kind = payload.get("类型")
    if not isinstance(kind, str) or not kind.strip():
        return {"错误": "query 缺少 类型"}
    if kind == "场景角色":
        pos = payload.get("位置")
        if not isinstance(pos, str) or "·" not in pos:
            return {"错误": "query 场景角色 须传入 位置（区域·场景）"}
        region, _, scene = pos.partition("·")
        chars = sc.scene_chars(payload.get("槽位"), region, scene)
        return {"界面": "query", "位置": pos, "区域人物": chars}
    derived = payload.get("派生", False)
    if not isinstance(derived, bool):
        return {"错误": "query 派生 须为布尔值"}
    return _dq.query_data(kind, payload.get("名称"), derived,
                          payload.get("字段"), payload.get("等级", 1))


def setting(payload=None):
    """门派/人物设定聚合查询。"""
    payload = {} if payload is None else payload
    error = _prepare_query(payload, "setting", {"槽位", "目标"})
    if error:
        return error
    target = payload.get("目标")
    if not isinstance(target, str) or not target.strip():
        return {"错误": "setting 缺少 目标"}
    return _dq.query_setting(target.strip())


def recommend(payload=None):
    """据阵营、一级属性与偏好推荐武学、心法和装备。"""
    payload = {} if payload is None else payload
    allowed = {"槽位", "姓名", "阵营", "一级属性", "武学偏好"}
    error = _prepare_query(payload, "recommend", allowed)
    if error:
        return error
    attrs = payload.get("一级属性")
    preference = payload.get("武学偏好")
    if not isinstance(attrs, dict):
        return {"错误": "recommend 一级属性 须为对象"}
    if not isinstance(preference, str) or not preference.strip():
        return {"错误": "recommend 缺少 武学偏好"}
    name = payload.get("姓名")
    faction = payload.get("阵营", "散人")
    if name is not None and not isinstance(name, str):
        return {"错误": "recommend 姓名 须为字符串"}
    if not isinstance(faction, str):
        return {"错误": "recommend 阵营 须为字符串"}
    try:
        return _dq.recommend_wuxue(name, faction, attrs, preference.strip())
    except ValueError as exc:
        return {"错误": f"recommend 参数错误：{exc}"}


def map_query(payload=None):
    """区域场景图或全区域配额查询。"""
    payload = {} if payload is None else payload
    error = _prepare_query(payload, "map-query", {"槽位", "区域"})
    if error:
        return error
    region = payload.get("区域")
    if not isinstance(region, str) or not region.strip():
        return {"错误": "map-query 缺少 区域"}
    return _map_query.query_map(region.strip(), payload["槽位"])


def _cli(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "go":
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(f"settle: JSON 解析失败（{e}）", file=sys.stderr)
            return 2
        # 格式：{"槽位": N, "行为":[...]}；槽位从 JSON 取，命令行不带
        if isinstance(payload, dict):
            slot = payload.get("槽位")
            actions = payload.get("行为") or []
        elif isinstance(payload, list):
            slot, actions = None, payload
        else:
            slot, actions = None, []
        if slot is None:
            print("用法: go（stdin 传 {\"槽位\": N, \"行为\": [...]}）", file=sys.stderr)
            return 2
        result = go(slot, actions)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if cmd == "check":
        # engine check（stdin 传 JSON：{"槽位": N, "属性":[...], "判定角色":[...],
        # "对抗":"角色名|@数值", "基础成功率": N}）
        # 正式 slot 且掷骰有效时落盘判定留痕（judge 据此核对是否带入剧情）。
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(f"check: JSON 解析失败（{e}）", file=sys.stderr)
            return 2
        result = check(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if "结果" in result else 2
    if cmd == "random-event":
        # engine random-event（stdin 传 JSON：{"槽位": N, "基础成功率": N}）
        # 判断是否触发随机事件，不落盘留痕（非技艺/属性判定）。
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(f"random-event: JSON 解析失败（{e}）", file=sys.stderr)
            return 2
        result = random_event(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if "结果" in result else 2
    if cmd in ("query", "setting", "recommend", "map-query"):
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(json.dumps({"错误": f"{cmd}: JSON 解析失败（{e}）"}, ensure_ascii=False, indent=2))
            return 2
        handlers = {
            "query": query,
            "setting": setting,
            "recommend": recommend,
            "map-query": map_query,
        }
        result = handlers[cmd](payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and result.get("错误") else 0
    if cmd == "judge":
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(f"judge: JSON 解析失败（{e}）", file=sys.stderr)
            return 2
        # 格式：{"槽位": N, "行为": [状态变更/战斗action...], "当前剧情": ..., "场景要素": [...], "经历概括": ...?}
        slot = payload.get("槽位")
        if slot is None:
            print("用法: judge（stdin 传 {\"槽位\": N, \"行为\": [...], \"当前剧情\": ...}）", file=sys.stderr)
            return 2
        result = judge(slot, payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print("未知命令: " + cmd + "\n可用: go / judge / check / random-event / query / setting / recommend / map-query", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        exit_code = _cli(sys.argv[1:])
    except JsonReadError as exc:
        print(json.dumps({"错误": str(exc), "错误代码": exc.code}, ensure_ascii=False, indent=2))
        exit_code = 2
    sys.exit(exit_code)
