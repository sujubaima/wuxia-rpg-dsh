#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大世界游历统一结算前端——go/judge 两步式。

- **engine go**：玩家主动指令的机制结算（休息/远行/使用物品/购买/出售/遣散/武学精进/
  战斗操控/配置/查询/存档等）。落盘机制后果，**不增轮次、不自动存档**。**返回带 `界面`
  则按对应渲染文档直接渲染**；以下情形**隐藏 `界面`、GM 据「无界面→调 judge」下调
  engine judge：空行为数组占位、休息/远行（徒步）/远行（舟车）/交谈观察/搜查翻找/其他行为，或战斗操控且战斗结束
  那一回合。普通配置/查询/存档类带 `界面` 直接渲染。
- **engine judge**：GM 基于 go 的既成结果推演后的裁定落盘。行为数组平铺一等状态变更
  条目（无剧情推动包壳）+ 顶层叙事字段（当前剧情必填/场景要素必填非空/经历概括）。任一状态
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
  python3 scripts/engine.py scene-prepare
  python3 scripts/engine.py quest-prepare
  python3 scripts/engine.py query
  python3 scripts/engine.py setting
  python3 scripts/engine.py recommend
  python3 scripts/engine.py map-query
"""
import copy
import os, sys
import json
from common import dao as dq
from common.json_io import JsonMissingError, JsonReadError, warn_json_read
from common.render_mode import render_mode
from store import save_manager as sm
from world import scene as sc
from settle import engine_state as est

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from settle.engine_io import _battle_last_path, _clear_battle_tmp, _set_slot, _sync_party
from settle.engine_ui import _build_response, _gm_autosave_hint, _inject_narrative, _norm_elements, _region_info, build_ui
from settle.engine_actions import (_ACTION_HANDLERS, _act_battle, _act_battle_advance,
                                   _act_battle_trigger, _apply_changes, _apply_narrative,
                                   _maybe_battle_end_ui, build_mutation_executor)
from quest.events import PLAYER_ACTION_COMPLETED
from settle.settlement import SettlementSession
from quest.triggers import build_quest_trigger_registry
from quest.conditions import referenced_facts
from quest.engine import (create_quest, extend_quest, modify_quest_rewards,
                       pending_extension_gates, validate_close_extension)
from quest.models import import_legacy_quests, normalize_quest_state
from quest.world_facts import normalize_world_facts
from settle.markdown_ui import attach_render_text
from store.tips import write_tips as _write_tips, read_tips as _read_tips
from store import quest_drafts as _quest_drafts
from store import scene_drafts as _scene_drafts
from store.battle_last import write_battle_last as _write_battle_last, battle_last_path as _battle_last_path
from store.check_log import missing_check_hints as _missing_check_hints, append_check as _append_check
from store import turn_state as _turn_state
from common import check as _check
from common import dao as _dq
from world import map_query as _map_query

# 功能场景类型 → 该功能NPC须支持的特殊指令（go 行为名）
_SCENE_TYPE_COMMANDS = {
    "驿站": ["远行（舟车）"],
    "店铺": ["购买", "出售"],
    "客栈": ["投宿"],
}
_SCENE_ELEMENT_DESCRIPTION_LIMIT = 30

# action 分发表
# 扣体力/时间集合（仅体力兜底与计费判定用，与「是否需 judge 推演」无关）
_STAMINA_COST_ACTIONS = {"攻击", "休息", "远行（徒步）", "远行（舟车）", "使用物品", "购买", "出售", "遣散", "交谈观察", "搜查翻找", "其他行为", "赠与物品"}

# 是否需 GM 下调 judge 推演，由 _build_response 返回的 界面 字段决定（无界面=交 GM），
# 不再按 action 类型集合判定（避免打开界面/结算同类型被误伤）。
# judge 专属 action（推演产物，产出战斗界面）：不接受于 go
_JUDGE_ACTIONS = {"战斗-开始", "战斗-触发", "战斗-推进"}

# 门厅哨兵槽位（slot<=0，前端未选存档）允许的动作：不依赖真 slot、不向 slot_0 落盘。
# 其余动作在哨兵槽位上一律拒绝，杜绝 slot 0 误落盘产生垃圾存档。
_LOBBY_SLOT0_ACTIONS = {"创建角色", "开始游戏", "标题-操作", "删除存档"}

_CONFIG_ACTIONS = {"配置装备", "配置物品", "配置武学", "武学精进",
                   "创建角色", "保存游戏", "加载存档", "删除存档", "开始游戏", "标题-操作", "存档列表", "角色信息", "查看背包", "武学列表",
                   "查看地图", "查看线索",
                   "战斗-使用武学", "战斗-使用物品", "战斗-休息", "战斗-逃跑", "战斗-认输", "战斗-处决",
                   "非法指令",
                   "返回游戏"}

_TURN_READ_ONLY_ACTIONS = {"开始游戏", "标题-操作", "存档列表", "返回游戏", "角色信息", "查看背包",
                           "武学列表", "查看地图", "查看线索", "非法指令"}
_BATTLE_GO_ACTIONS = {"战斗-使用武学", "战斗-使用物品", "战斗-休息",
                      "战斗-逃跑", "战斗-认输", "战斗-处决"}
_DOMAIN_ACTIONS = {
    "休息", "远行（徒步）", "远行（舟车）", "使用物品", "购买", "出售", "赠与物品",
    "遣散", "武学精进", "配置装备", "配置物品", "配置武学", "其他行为", "交谈观察", "搜查翻找", "攻击",
}
_ACTION_EVENT_FIELDS = ("角色", "目标", "物品", "武学", "目的地", "赠送者", "受赠者",
                        "买家", "卖家", "数量", "等级", "时长", "操作")


def _action_event_payload(action):
    payload = {"action": action.get("类型")}
    params = {key: action[key] for key in _ACTION_EVENT_FIELDS if key in action}
    if params:
        payload["parameters"] = params
    return payload


def _public_results(results):
    return [
        {key: value for key, value in result.items() if not str(key).startswith("_")}
        for result in results if not result.get("_静默")
    ]


def _attach_quest_hints(response, hints):
    if hints and isinstance(response, dict):
        response["GM线索提示"] = hints
    return response


def _action_list(actions):
    if isinstance(actions, dict):
        return [actions]
    return actions if isinstance(actions, list) else []


def _is_turn_read_only(actions):
    items = _action_list(actions)
    return bool(items) and all(
        isinstance(action, dict) and action.get("类型") in _TURN_READ_ONLY_ACTIONS
        for action in items
    )


def _is_restore_only(actions):
    items = _action_list(actions)
    return len(items) == 1 and isinstance(items[0], dict) and items[0].get("类型") == "加载存档"


def _is_delete_only(actions):
    """删除存档是跨回合的存档管理操作，任何回合状态下都放行（同 加载存档 待遇）。"""
    items = _action_list(actions)
    return len(items) == 1 and isinstance(items[0], dict) and items[0].get("类型") == "删除存档"


_SLOT_POLICY_LOBBY = "lobby"
_SLOT_POLICY_CLAIM = "claim"
_SLOT_POLICY_EXISTING = "existing"
_CLAIM_ACTIONS = {"创建角色"}
_LOBBY_ACTIONS = {"开始游戏", "标题-操作"}


def _claim_batch_valid(actions):
    items = _action_list(actions)
    exclusive = [a for a in items if isinstance(a, dict)
                 and a.get("类型") in (_CLAIM_ACTIONS | {"加载存档"})]
    return not exclusive or (len(items) == 1 and len(exclusive) == 1)


def _go_slot_policy(slot, actions):
    items = _action_list(actions)
    types = {a.get("类型") for a in items if isinstance(a, dict)}
    if types & _CLAIM_ACTIONS:
        return _SLOT_POLICY_CLAIM
    if types and types <= _LOBBY_ACTIONS:
        return _SLOT_POLICY_LOBBY
    if not sm._slot_writable(slot):
        return _SLOT_POLICY_LOBBY
    return _SLOT_POLICY_EXISTING


def _turn_origin(actions):
    types = {action.get("类型") for action in _action_list(actions)
             if isinstance(action, dict)}
    if types == {"创建角色"}:
        return "创建角色"
    return "战斗操控" if types and types <= _BATTLE_GO_ACTIONS else "普通行动"


# 新档开场白·时代背景固定模板（exploration-rules「新档开场白」同文；judge 校验首句，缺失即打回）
OPENING_ERA_TEMPLATE = (
    "大明万历年间，天下承平日久，江湖却暗流渐起。\n\n"
    "西域流沙之间，昔年被中原武林联手剿灭的无极教，竟以幽冥宫之名东山再起，"
    "兵锋渐指中原。而中原门派却各怀隐患，辽东与西南也隐有战端。江湖危机一触即发。"
)
OPENING_ERA_SENTENCE = "大明万历年间，天下承平日久，江湖却暗流渐起。"


def _contains_opening_template(payload):
    """开场白校验：当前剧情 须包含时代背景模板首句（GM 引了首句不会漏掉其余，免比对换行差异）。"""
    narrative = payload.get("当前剧情")
    return isinstance(narrative, str) and OPENING_ERA_SENTENCE in narrative


def _turn_error(slot, code, message, state):
    return {
        "槽位": slot,
        "错误": message,
        "状态冲突": code,
        "turn_state": state,
    }


def _with_turn_state(result, state):
    if isinstance(result, dict):
        result["turn_state"] = state
    return result


def _settle_go(slot, actions=None):
    """engine go：玩家主动指令的机制结算。落盘机制后果（角色/explore 体力/时间/位置/队伍），
    不推进世界轮次、不触发自动存档（轮次仅由 judge 推进）。
    返回带 `界面` 字段——GM 据此直接读对应渲染文档；以下情形**隐藏 `界面`**（空行为数组占位、休息/远行（徒步）/
    远行（舟车）/交谈观察/搜查翻找/其他行为，或战斗操控且战斗结束那一回合），GM 据「无界面→调 judge」下调 engine judge
    （judge 始终保留 `界面`）。"""
    _set_slot(slot)
    if isinstance(actions, dict):
        actions = [actions]
    actions = actions or []
    # 正式槽位的空数组是“全部行动受剧情约束阻止”的占位协议：不结算成本，
    # 默认无界面并由 go() 进入 AWAITING_JUDGE，交给 judge 叙述受阻结果。

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

    results = []
    bt_data = None  # 战斗操控 action 的 battle-ui 数据
    party_changes = []  # 本轮在队变更（成功者），用于同步 explore.队伍
    executor = build_mutation_executor()
    quest_hints = []
    quest_triggers = None if _is_restore_only(valid) else build_quest_trigger_registry()
    with SettlementSession(slot, explore, executor, "go", quest_triggers) as session:
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
            action_ok = all(r.get("ok") for r in rs)
            if action_ok and t in _DOMAIN_ACTIONS:
                rs += session.emit(PLAYER_ACTION_COMPLETED, _action_event_payload(a), "go")
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
            results = _public_results(results)
            return _build_response(slot, valid, False, sm.rounds_until_save(slot), results,
                                   error="操作失败：" + "；".join(err_msgs))
        session.commit()
        results.extend(session.public_notice_results())
        quest_hints = list(session.gm_hints)
        results = _public_results(results)

    if party_changes:
        _sync_party(slot, explore, party_changes)

    # 推进世界判定：玩家主动行为类，或战斗操控且本轮战斗结束
    # 战斗操控：落盘 explore + 缓存引擎战报（battle_last.json）；非终局 go 无界面，
    # 随后由 judge 战斗-推进 打包 battle-ui（每回合 go/judge 两步式）。
    if bt_data is not None:
        sm.write_explore(slot, explore, preserve_narrative=True)
        status = (bt_data.get("战局状态") or {}).get("状态")
        if status and status != "进行中":
            bt_data.update(_region_info(slot, explore))  # 战后处置路线参考（区域提示+区域人物）
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
        # 非终局无界面时不改数据；直接胜利产生 battle-end-ui 时在此挂载 Markdown。
        attach_render_text(bt_data)
        return _attach_quest_hints(bt_data, quest_hints)

    # 存档/建档/读档 handler 内部已重写 explore.json，不再覆盖
    save_related = {"创建角色", "保存游戏", "加载存档", "删除存档"}
    # 纯只读/查询动作（不改 explore）：回写会凭空刷新 mtime、甚至给未建档 slot
    # 写出空 explore.json 造垃圾目录，故一律跳过回写。
    read_only = {"开始游戏", "标题-操作", "存档列表", "返回游戏", "角色信息", "查看背包",
                 "武学列表", "查看地图", "查看线索", "非法指令"}
    types = {a.get("类型") for a in valid}
    if (explore
            and not (types & save_related)
            and not (types <= read_only)):
        sm.write_explore(slot, explore, preserve_narrative=True)

    # 建档时 stdin 槽位≠新档：剩余/tips/区域信息均须按新 slot 取（其余动作 state_slot==slot 无感）
    state_slot = slot
    created_slot = None
    for r in results:
        if r.get("新建slot"):
            state_slot = r["新建slot"]
            created_slot = r["新建slot"]
            break
    resp = _build_response(slot, valid, False, sm.rounds_until_save(state_slot), results)
    # 无界面 → 需 GM 推演：补区域提示与区域人物供 GM 设计路线/登场角色；GM 据此下调 judge。
    # 有界面（子界面/弹窗/exploration-ui）→ 前端直接渲染，不补区域信息。
    if resp.get("界面") is None:
        # 建档路径 handler 已自行落盘新 slot 的 explore，进程开头的内存 explore 为空，须重读
        slot_explore = (sm.read_explore(state_slot) or {}) if created_slot is not None else explore
        resp.update(_region_info(state_slot, slot_explore))
        # 推演前强制判定思考提示：GM 下调 judge 前必先回溯本回合是否该判
        resp["GM提示"] = "推演剧情前先自问：本回合剧情发展是否依赖角色某项技艺/属性水平高低？涉及即先调 wuxia_check（不可用时 engine check）掷骰，并据结果推演。"
    # 只读 go 不得覆盖待 judge 的机制提示；其他 go 仍覆盖写并由 judge 消费一次。
    if not (types <= read_only):
        _write_tips(state_slot, results)
    return _attach_quest_hints(resp, quest_hints)

def _dead_element_hits(elements):
    """死亡角色红线核对：返回场景要素主体命中的死亡角色 [(主体, 角色名), ...]。

    主体匹配取最长角色名（避免短名误伤更长的相似名）；「角色名+的+…」视为
    尸体/遗物/旧地等非正面登场表述，放行。校验先于状态变更落盘，
    本轮才判死亡的角色尚未标记，可正常同轮收尾登场。"""
    try:
        chars = dq.load_all("角色")
    except (JsonMissingError, JsonReadError) as exc:
        if isinstance(exc, JsonReadError):
            warn_json_read(exc)
        return []
    dead = {name for name, rec in chars.items() if rec.get("死亡")}
    if not dead:
        return []
    names = sorted(chars, key=len, reverse=True)  # 最长优先：首个命中的即最佳匹配
    hits = []
    for element in elements:
        sub = str(element.get("主体") or "").strip()
        if not sub:
            continue
        matched = next((n for n in names
                        if sub == n or sub.startswith(n) or sub.endswith(n)), None)
        if matched not in dead:
            continue
        if sub == matched:
            hits.append((sub, matched))
        elif sub.startswith(matched):
            if not sub[len(matched):].startswith("的"):
                hits.append((sub, matched))
        else:  # 头衔前缀引用（如「水寨头领薛四彭」）；「…的+名」视为指代遗存放行
            if not sub[:-len(matched)].endswith("的"):
                hits.append((sub, matched))
    return hits

def _player_element_hits(slot, elements, changes=None):
    """玩家主控红线核对：返回场景要素主体命中主控角色名的 [主体, ...]。

    主控状态由队伍面板承载，重复申报为要素会挤占要素位并误导交互。
    主体匹配与死亡红线同口径：最长角色名优先（避免短名误伤相似长名）；
    「角色名+的+…」视为随身物件等非本人表述，放行。本轮 写角色 的新名
    一并纳入消歧（校验先于落盘，同轮新登场的相似长名不误伤）。"""
    player = str((sm.read_meta(slot) or {}).get("角色名") or "").strip()
    if not player:
        return []
    try:
        chars = dq.load_all("角色")
    except (JsonMissingError, JsonReadError) as exc:
        if isinstance(exc, JsonReadError):
            warn_json_read(exc)
        return []
    if player not in chars:
        return []
    names = set(chars)
    for c in changes or []:
        if isinstance(c, dict) and c.get("类型") == "写角色" and isinstance(c.get("角色"), dict):
            new_name = str(c["角色"].get("名称") or "").strip()
            if new_name:
                names.add(new_name)
    ordered = sorted(names, key=len, reverse=True)  # 最长优先：首个命中的即最佳匹配
    hits = []
    for element in elements:
        sub = str(element.get("主体") or "").strip()
        if not sub:
            continue
        matched = next((n for n in ordered
                        if sub == n or sub.startswith(n) or sub.endswith(n)), None)
        if matched != player:
            continue
        if sub == matched:
            hits.append(sub)
        elif sub.startswith(matched):
            if not sub[len(matched):].startswith("的"):
                hits.append(sub)
        else:  # 头衔前缀引用；「…的+名」视为指代随身物件放行
            if not sub[:-len(matched)].endswith("的"):
                hits.append(sub)
    return hits

def _settle_judge(slot, changes=None, narrative=None):
    """engine judge：GM 基于 go 的既成状态（go 已落盘机制后果）推演后，裁定落盘。

    changes：行为数组，元素为两类——
      · 状态变更条目（{类型:铜钱/经验/关系度/物品/装备/在队/气血/内力/死亡/时间/抵达/
        场景-采用草稿/事实/线索-采用草稿/线索-发现/武学/体力/战斗-结束...}），经 _apply_changes 裁定
        （战斗-结束：战斗整场耗时耗力——体力-20/时间+8刻，自动结算，战后处置必带）；
      · 独立 action 条目（战斗-开始/战斗-触发），单独 dispatch 产出 battle-ui。
    narrative：顶层叙事字段 {当前剧情(必填)/场景要素(必填非空，战斗类豁免)/经历概括/提及地点(必填，可为空数组)}。
    提及地点：本轮叙事新提及、玩家可前往的「区域·场景」全名数组；正式地图或本轮场景草稿中未登记则打回。
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
    # 场景要素为强制申报：缺省或空数组会让玩家界面沿用上一轮旧要素
    # （功能场景甚至残留过期特殊指令），非战斗 judge 必须显式重报本轮非空要素；
    # 战斗类 judge 豁免（界面由战报直出，同 当前剧情/提及地点 的豁免口径）。
    if not has_battle_entry and not elements:
        return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                               error="judge 须传非空「场景要素」数组（本轮可见的人/物/环境，"
                                     "每项 {主体, 描写}；不得缺省或传空数组，无变化也须重报现状）",
                               gm_error=True)
    if elements is not None:
        elements = _norm_elements(elements)
        if elements is None:
            return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                   error="judge `场景要素` 须为 {主体, 描写} 对象数组（主体必填）",
                                   gm_error=True)
        for element in elements:
            description = element.get("描写") or ""
            if len(description) > _SCENE_ELEMENT_DESCRIPTION_LIMIT:
                return _build_response(
                    slot, [], False, sm.rounds_until_save(slot), [],
                    error=(f"judge 场景要素【{element['主体']}】的 描写 不得超过"
                           f"{_SCENE_ELEMENT_DESCRIPTION_LIMIT}字（当前{len(description)}字）"),
                    gm_error=True,
                )

    # 死亡角色红线：主体命中 死亡=true 的角色即打回（死于本轮者尚未落盘，可同轮收尾登场）；
    # 尸体/遗物/旧地等以「角色名+的+…」主体表述放行。
    if elements:
        dead_hits = _dead_element_hits(elements)
        if dead_hits:
            detail = "；".join(f"【{sub}】命中死亡角色【{name}】" for sub, name in dead_hits)
            return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                   error=f"死亡角色不得申报为场景要素主体：{detail}——"
                                         "死亡角色不得正面登场；若为尸体/遗物/旧地等，"
                                         "请改用「角色名+的+…」主体表述、名称写入描写",
                                   gm_error=True)

    # 玩家主控红线：主控状态由队伍面板承载，要素主体不得再申报主控本人
    #（随身物件以「角色名+的+…」主体表述放行，与死亡红线同口径）。
    if elements:
        player_hits = _player_element_hits(slot, elements, changes)
        if player_hits:
            detail = "；".join(f"【{sub}】" for sub in player_hits)
            return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                   error=f"玩家主控不得申报为场景要素主体：{detail}——"
                                         "主控状态由队伍面板承载，请勿重复申报；"
                                         "若指随身物件，请改用「角色名+的+…」主体表述",
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

    # 提及地点自查核对：非战斗轮必须显式申报「提及地点」（可为空数组，不得缺省），
    # 条目须为「区域·场景」全名。正式地图或本轮已采用草稿中存在则通过；否则打回，
    # 不可达/无需涉足则移出申报。战斗类 judge 跳过（同判定留痕：战时不增负担）。
    if not has_battle_entry:
        reported = narrative.get("提及地点")
        if not isinstance(reported, list):
            return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                   error="judge 须传「提及地点」数组（本轮叙事新提及、玩家可前往的"
                                         "「区域·场景」全名，可为空 []，不得缺省）",
                                   gm_error=True)
        names = list(dict.fromkeys(str(x).strip() for x in reported if str(x).strip()))
        malformed = [name for name in names if "·" not in name]
        if malformed:
            return _build_response(
                slot, [], False, sm.rounds_until_save(slot), [],
                error=f"提及地点须为「区域·场景」全名：{'、'.join(malformed)}——请补全区域前缀后重试",
                gm_error=True)
        registered_now = set()
        if any(c.get("类型") == "场景-采用草稿" for c in change_entries):
            try:
                scene_batch = _scene_drafts.select_draft(slot)
            except (JsonReadError, ValueError) as exc:
                detail = exc.detail if isinstance(exc, JsonReadError) else str(exc)
                return _build_response(
                    slot, [], False, sm.rounds_until_save(slot), [],
                    error=f"场景草稿读取失败，须重新 scene-prepare（{detail}）",
                    gm_error=True,
                )
            registered_now.update(
                (operation.get("区域"), operation.get("场景"))
                for operation in scene_batch["operations"]
                if operation.get("类型") == "登记场景"
            )
        unregistered = []
        for name in names:
            region, _, scene = name.partition("·")
            if ((region, scene) not in registered_now
                    and scene not in (sc.merged_scenes(slot, region) or {})):
                unregistered.append(name)
        if unregistered:
            return _build_response(
                slot, [], False, sm.rounds_until_save(slot), [],
                error=f"提及地点未登记：{'、'.join(unregistered)}——若允许玩家前往，请先用 "
                      f"scene-prepare 准备登记并在 judge 加入「场景-采用草稿」；若不可达或无需涉足，"
                      f"请将其从「提及地点」中移除",
                gm_error=True)

    # go 的机制后果提示在前：judge 每回合读 tips.json（成功消费后清空，失败保留重调），
    # 把 go 的变更行拼到本次 结算 最前。文件由 go 单方覆盖更新（有则写入、无则空数组）。
    tips = _read_tips(slot)
    # 事务态：judge 的 mutation、领域事件与触发结果整体结算
    results = []
    bt_data = None
    party_changes = []
    executor = build_mutation_executor()
    quest_hints = []
    with SettlementSession(slot, explore, executor, "judge", build_quest_trigger_registry()) as session:
        # 先应用状态变更，使同轮「写角色」进入事务暂存区，供战斗-触发校验参战者。
        # 成功且在队变更需记，用于提交后同步 explore.队伍。
        for r in _apply_changes(slot, explore, change_entries):
            results.append(r)
            if r.get("ok") and r.get("_在队变更"):
                party_changes.append(r["_在队变更"])

        # 经历概括（叙事定稿；失败打 _结算错误）
        if narrative.get("经历概括") is not None:
            results += _apply_narrative(slot, explore, narrative.get("经历概括"))

        # 前置变更均有效后再产出战斗界面；失败则不启动战斗或返回战前界面。
        if all(r.get("ok") for r in results):
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

        all_ok = all(r.get("ok") for r in results)
        if not all_ok:
            failed = [r for r in results if not r.get("ok")]
            err_msgs = [r["msg"] for r in failed]
            results = _public_results(results)
            return _build_response(slot, [], False, sm.rounds_until_save(slot), results,
                                   error="judge 状态变更结算异常：" + "；".join(err_msgs),
                                   gm_error=True)

        # 红线（功能NPC必露脸+特殊指令）：状态变更落盘后，特殊指令只能出现在当前场景
        # 绑定的功能NPC要素上，且须严格匹配场景功能（驿站→远行（舟车），店铺→购买/出售，
        # 客栈→投宿）。普通NPC、物件和环境要素不得携带特殊指令。
        # 校验置于变更应用之后，使 抵达/远行 改变位置后的新场景亦受约束。
        if elements is not None:
            cur_pos = explore.get("当前位置") or ""
            cur_region, _, cur_scene = cur_pos.partition("·")
            stype = sc.scene_type(slot, cur_region, cur_scene, staged=est._SCENE_TYPE_STAGED)
            npc = sc.scene_npc(slot, cur_region, cur_scene, staged=est._SCENE_TYPE_STAGED)
            req_cmds = _SCENE_TYPE_COMMANDS.get(stype) if stype else None
            command_elements = [e for e in elements if e.get("特殊指令")]

            for element in command_elements:
                subject = str(element.get("主体") or "")
                if not (npc and req_cmds and subject.startswith(npc)):
                    if npc and req_cmds:
                        error = (f"场景要素【{subject}】不是当前场景绑定的功能NPC【{npc}】，"
                                 "不得携带特殊指令")
                    else:
                        error = (f"当前场景【{cur_scene}】无绑定功能NPC，"
                                 f"场景要素【{subject}】不得携带特殊指令")
                    return _build_response(slot, [], False, sm.rounds_until_save(slot), results,
                                           error=error, gm_error=True)

            if npc and req_cmds:
                npc_elements = [e for e in elements
                                if str(e.get("主体") or "").startswith(npc)]
                if not npc_elements:
                    return _build_response(slot, [], False, sm.rounds_until_save(slot), results,
                                           error=f"当前场景【{cur_scene}】为功能场景，`场景要素` 必含一条主体以功能NPC【{npc}】开头的要素",
                                           gm_error=True)
                have = [c.get("名称") for e in npc_elements
                        for c in (e.get("特殊指令") or []) if isinstance(c, dict)]
                missing = [c for c in req_cmds if c not in have]
                extra = [c for c in have if c not in req_cmds]
                duplicate = len(have) != len(set(have))
                if missing or extra or duplicate:
                    details = []
                    if missing:
                        details.append(f"缺少 {missing}")
                    if extra:
                        details.append(f"不允许 {extra}")
                    if duplicate:
                        details.append("存在重复指令")
                    return _build_response(
                        slot, [], False, sm.rounds_until_save(slot), results,
                        error=f"功能NPC【{npc}】的特殊指令须严格为 {req_cmds}（{'；'.join(details)}）",
                        gm_error=True,
                    )

        # 打回校验：任务已行进至扩展点（前置齐、条件真、未激活）而本轮未扩展。
        # 整体打回（commit 前，磁盘零写入；tips 与回合号原样保留供重调），
        # GM 须 quest-prepare 准备扩展、经 线索-采用草稿 采纳后重新 judge。
        # 战斗类 judge 豁免（只提示不打回），避免战斗中强制插入扩展；战后普通 judge 再拦。
        gates = pending_extension_gates(session.world_facts, session.quest_state)
        if gates and battle_entries:
            session.add_hints([{
                "类型": "任务扩展", "线索": quest_name, "扩展点": node_id,
                "提示": (f"任务【{quest_name}】已行进至扩展点【{node_id}】，"
                         "战斗结束后须先 quest-prepare 准备扩展，或以 关闭 操作强关该扩展点"),
            } for quest_name, node_id in gates])
        elif gates:
            described = "；".join(
                f"任务【{quest_name}】扩展点【{node_id}】" for quest_name, node_id in gates
            )
            return _build_response(
                slot, [], False, sm.rounds_until_save(slot), results,
                error=(f"{described}已到达但未扩展：本轮 judge 打回，"
                       "须先以 quest-prepare 准备该扩展点的扩展蓝图，"
                       "并在 judge 行为中经 线索-采用草稿 采纳后重新提交；"
                       "若该方向无继续推演必要，可以 关闭 操作强关该扩展点"),
                gm_error=True,
            )

        # 全过 → 叙事落 explore + 角色改动/场景登记统一落盘
        if plot and str(plot).strip():  # 战斗类 judge 允许空剧情（战斗推进无探索叙事），空则不覆盖
            explore["当前剧情"] = plot
        if elements is not None:
            explore["场景要素"] = elements
        session.commit()
        results.extend(session.public_notice_results())
        quest_hints = list(session.gm_hints)
        results = _public_results(results)

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
        bt_data["渲染模式"] = render_mode()
        attach_render_text(bt_data)  # 战前选择、战斗中与胜利终局界面统一挂载 Markdown
        return _attach_quest_hints(bt_data, quest_hints)

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

    # GM 是经历概括的作者、任务通知每轮都在结算里；历史保留工具组后周期性回显全量
    # 概括/线索栏已成冗余，需要时用 查看线索 随时查询（加载存档轮仍随 go 返回以恢复上下文）

    # 战后处置落盘完成：清理该 slot 的战斗临时文件（避免「返回游戏」误判战斗中）
    _clear_battle_tmp(slot)

    # exploration-ui：拼公共字段 + build_ui 取状态与叙事（narrative 已落 explore.json）
    base = {"saved": saved, "剩余": sm.rounds_until_save(slot), "结算": results, "槽位": slot}
    if saved:
        base["GM参考"] = _gm_autosave_hint(slot)
    ctx = {"explore": explore, "narrative": {"当前剧情": plot, "场景要素": elements},
           "results": results}
    base.update(build_ui(slot, "exploration-ui", ctx))
    if "界面" in base:
        base["渲染模式"] = render_mode()
        attach_render_text(base)
    return _attach_quest_hints(base, quest_hints)

def go(slot, actions=None):
    """engine go 入口：按槽位策略执行结算并统一迁移回合状态。

    正式槽位传空 actions 表示本轮所有行动均受剧情约束阻止，仅占位进入 judge。
    """
    if not _claim_batch_valid(actions):
        return _build_response(
            slot, [], False, sm.rounds_until_save(slot), [],
            error="创建角色或加载存档必须作为唯一 action 单独提交",
        )

    policy = _go_slot_policy(slot, actions)
    if policy == _SLOT_POLICY_LOBBY:
        return _settle_go(slot, actions)

    if policy == _SLOT_POLICY_EXISTING and _is_turn_read_only(actions):
        result = _settle_go(slot, actions)
        try:
            state = _turn_state.read_state(slot)["state"]
        except JsonReadError:
            return result
        return _with_turn_state(result, state)

    state = _turn_state.READY
    restore_only = _is_restore_only(actions)
    delete_only = _is_delete_only(actions)
    if policy == _SLOT_POLICY_EXISTING:
        turn = _turn_state.read_state(slot)
        state = turn["state"]
        if state != _turn_state.READY and not restore_only and not delete_only:
            if state == _turn_state.AWAITING_JUDGE:
                return _turn_error(
                    slot,
                    "go_already_committed",
                    "上一条 go 已完成机制结算，须沿用其返回继续 judge，不得重复执行 go",
                    state,
                )
            return _turn_error(
                slot,
                "battle_start_expected",
                "战斗已进入战前选择阶段，只允许提交 judge 战斗-开始",
                state,
            )

    result = _settle_go(slot, actions)
    if result.get("错误"):
        if policy == _SLOT_POLICY_CLAIM:
            return result
        return _with_turn_state(result, state)

    state_slot = result.get("槽位", slot)
    if not sm._slot_writable(state_slot):
        return result
    if restore_only:
        new_state = _turn_state.reset_state(state_slot)
        return _with_turn_state(result, new_state["state"])
    if result.get("界面") is not None:
        return _with_turn_state(result, _turn_state.READY)

    new_state = _turn_state.write_state(
        state_slot,
        _turn_state.AWAITING_JUDGE,
        origin=_turn_origin(actions),
    )
    return _with_turn_state(result, new_state["state"])


def judge(slot, payload=None):
    """engine judge 入口：GM 推演后的裁定落盘。
    payload: {"槽位":N(由调用方剥离), "行为":[...], "当前剧情":..., "场景要素":[...], "经历概括":...}
    顶层仅允许 行为/当前剧情/场景要素/经历概括 四字段；其余（如把线索/状态变更误放顶层）
    一律报错，避免静默忽略。"""
    payload = payload or {}
    if not sm._slot_writable(slot):
        allowed_top = {"槽位", "行为", "当前剧情", "场景要素", "经历概括", "提及地点"}
        extra = set(payload.keys()) - allowed_top
        if extra:
            return _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                   error=f"judge 顶层出现非预期字段：{('、'.join(sorted(extra)))}。"
                                         f"仅允许 行为/当前剧情/场景要素/经历概括/提及地点；"
                                         f"状态变更（如线索）须放「行为」数组内",
                                   gm_error=True)
        narrative = {k: payload[k] for k in ("当前剧情", "场景要素", "经历概括", "提及地点")
                     if k in payload}
        return _settle_judge(slot, payload.get("行为"), narrative)

    turn = _turn_state.read_state(slot)
    state = turn["state"]
    actions = payload.get("行为")
    items = _action_list(actions)
    battle_start_only = (
        len(items) == 1
        and isinstance(items[0], dict)
        and items[0].get("类型") == "战斗-开始"
    )
    has_battle_start = any(
        isinstance(item, dict) and item.get("类型") == "战斗-开始"
        for item in items
    )
    if state == _turn_state.READY:
        return _turn_error(
            slot,
            "judge_not_expected",
            "当前没有等待裁定的 go，不能提交 judge",
            state,
        )
    if state == _turn_state.AWAITING_BATTLE_START and not battle_start_only:
        return _turn_error(
            slot,
            "battle_start_expected",
            "战斗已进入战前选择阶段，只允许提交唯一的 judge 战斗-开始",
            state,
        )
    if state == _turn_state.AWAITING_JUDGE and has_battle_start:
        return _turn_error(
            slot,
            "battle_start_not_expected",
            "尚未完成 judge 战斗-触发，不能开始战斗",
            state,
        )

    if state == _turn_state.AWAITING_JUDGE:
        direct_scene = [
            item.get("类型") for item in items
            if isinstance(item, dict) and item.get("类型") in {"登记场景", "隔离地点"}
        ]
        if direct_scene:
            result = _build_response(
                slot, [], False, sm.rounds_until_save(slot), [],
                error="judge 不再直接接受「登记场景/隔离地点」；请先 scene-prepare，"
                      "再在 judge 行为中提交「场景-采用草稿」",
                gm_error=True,
            )
            return _with_turn_state(result, state)
        adoptions = [
            item for item in items
            if isinstance(item, dict) and item.get("类型") == "场景-采用草稿"
        ]
        if len(adoptions) > 1:
            result = _build_response(
                slot, [], False, sm.rounds_until_save(slot), [],
                error="judge 每轮最多提交一次「场景-采用草稿」", gm_error=True,
            )
            return _with_turn_state(result, state)
        try:
            scene_draft = _scene_drafts.read_draft(slot)
        except JsonReadError as exc:
            result = _build_response(
                slot, [], False, sm.rounds_until_save(slot), [],
                error=f"场景草稿读取失败，须重新 scene-prepare（{exc.detail}）", gm_error=True,
            )
            return _with_turn_state(result, state)
        has_scene_draft = bool(scene_draft.get("operations"))
        if has_scene_draft and not adoptions:
            result = _build_response(
                slot, [], False, sm.rounds_until_save(slot), [],
                error="本轮已有未采纳的场景草稿；请在 judge 行为中加入「场景-采用草稿」，"
                      "或用 scene-prepare 传空「场景」数组清除草稿",
                gm_error=True,
            )
            return _with_turn_state(result, state)
        if adoptions and not has_scene_draft:
            result = _build_response(
                slot, [], False, sm.rounds_until_save(slot), [],
                error="本轮没有可采用的场景草稿，请先 scene-prepare", gm_error=True,
            )
            return _with_turn_state(result, state)
        if adoptions:
            actions = adoptions + [item for item in items if item not in adoptions]

    _ALLOWED_TOP = {"槽位", "行为", "当前剧情", "场景要素", "经历概括", "提及地点"}
    extra = set(payload.keys()) - _ALLOWED_TOP
    if extra:
        result = _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                 error=f"judge 顶层出现非预期字段：{('、'.join(sorted(extra)))}。"
                                       f"仅允许 行为/当前剧情/场景要素/经历概括/提及地点；"
                                       f"状态变更（如线索）须放「行为」数组内",
                                 gm_error=True)
        return _with_turn_state(result, state)
    if (state == _turn_state.AWAITING_JUDGE
            and turn.get("origin") == "创建角色"
            and not _contains_opening_template(payload)):
        result = _build_response(slot, [], False, sm.rounds_until_save(slot), [],
                                 error="新档开场 judge 的「当前剧情」缺少固定开场白（时代背景模板），"
                                       "请将下段完整写入当前剧情后重新提交 judge：\n"
                                       + OPENING_ERA_TEMPLATE,
                                 gm_error=True)
        return _with_turn_state(result, state)
    narrative = {k: payload[k] for k in ("当前剧情", "场景要素", "经历概括", "提及地点")
                 if k in payload}
    judge_round = sm.read_round(slot)
    result = _settle_judge(slot, actions, narrative)
    if result.get("错误"):
        return _with_turn_state(result, state)
    try:
        _quest_drafts.clear_round(slot, judge_round)
    except (JsonReadError, OSError):
        # judge 权威状态已经提交；清理失败不能把成功伪装成失败，旧草稿仍受阶段/round 门禁约束。
        pass
    try:
        _scene_drafts.clear_round(slot, judge_round)
    except (JsonReadError, OSError):
        pass
    if result.get("界面") == "exploration-battle-ui":
        new_state = _turn_state.write_state(
            slot,
            _turn_state.AWAITING_BATTLE_START,
            origin=turn.get("origin"),
        )
    else:
        new_state = _turn_state.reset_state(slot)
    return _with_turn_state(result, new_state["state"])


def check(payload=None):
    """属性/技艺判定；有效结果写入当前轮判定留痕。"""
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        return {"错误": "check stdin 须为 JSON 对象"}
    slot = payload.get("槽位")
    if slot is None:
        return {"错误": "check 缺少 槽位"}
    if sm._slot_writable(slot):
        state = _turn_state.read_state(slot)["state"]
        if state != _turn_state.AWAITING_JUDGE:
            return _turn_error(
                slot,
                "check_not_expected",
                "check 只允许在 go 已完成、等待 judge 时调用",
                state,
            )
    else:
        state = None
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
    return _with_turn_state(result, state) if state else result


def random_event(payload=None):
    """随机事件判定；切换槽位但不写判定留痕。"""
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        return {"错误": "random-event stdin 须为 JSON 对象"}
    slot = payload.get("槽位")
    if slot is None:
        return {"错误": "random-event 缺少 槽位"}
    if sm._slot_writable(slot):
        state = _turn_state.read_state(slot)["state"]
        if state != _turn_state.AWAITING_JUDGE:
            return _turn_error(
                slot,
                "random_event_not_expected",
                "random-event 只允许在 go 已完成、等待 judge 时调用",
                state,
            )
    else:
        state = None
    _dq.set_slot(slot)
    result = _check.run_random_event(payload.get("基础成功率", 15))
    return _with_turn_state(result, state) if state else result


def scene_prepare(payload=None):
    """批量预校验场景登记/隔离/重连，并保存当前 round 最新草稿。"""
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        return {"ok": False, "错误": "scene-prepare stdin 须为 JSON 对象"}
    slot = payload.get("槽位")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot <= 0:
        return {"ok": False, "错误": "scene-prepare 缺少有效正式 槽位"}
    turn = _turn_state.read_state(slot)
    state = turn["state"]
    if state != _turn_state.AWAITING_JUDGE:
        result = _turn_error(
            slot,
            "scene_prepare_not_expected",
            "scene-prepare 只允许在 go 已完成、等待 judge 时调用",
            state,
        )
        result["ok"] = False
        return result

    extra = set(payload) - {"槽位", "场景"}
    if extra:
        return _with_turn_state({
            "ok": False, "槽位": slot,
            "错误": f"scene-prepare 出现非预期字段：{'、'.join(sorted(extra))}",
        }, state)
    items = payload.get("场景")
    if not isinstance(items, list):
        return _with_turn_state({
            "ok": False, "槽位": slot, "错误": "scene-prepare 场景 须为数组",
        }, state)

    round_number = sm.read_round(slot)
    if not items:
        _scene_drafts.write_batch(slot, round_number, [])
        return _with_turn_state({"ok": True, "槽位": slot, "场景": [], "已清除": True}, state)

    normalized = []
    summaries = []
    for index, item in enumerate(items, 1):
        prefix = f"scene-prepare 第 {index} 项"
        if not isinstance(item, dict):
            return _with_turn_state({"ok": False, "槽位": slot,
                                     "错误": f"{prefix}须为对象"}, state)
        operation = item.get("操作")
        if operation == "登记":
            allowed = {"操作", "区域", "场景", "方位出口", "功能类型", "功能NPC"}
            mutation = {"类型": "登记场景", **{k: copy.deepcopy(v) for k, v in item.items()
                                              if k != "操作"}}
            operations = [mutation]
        elif operation == "隔离":
            allowed = {"操作", "区域", "场景"}
            operations = [{"类型": "隔离地点", "区域": item.get("区域"),
                           "场景": item.get("场景")}]
        elif operation == "重连":
            allowed = {"操作", "区域", "场景", "方位出口"}
            exits = item.get("方位出口")
            if not isinstance(exits, dict) or not exits:
                return _with_turn_state({"ok": False, "槽位": slot,
                                         "错误": f"{prefix}重连须提供非空 方位出口"}, state)
            operations = [
                {"类型": "隔离地点", "区域": item.get("区域"), "场景": item.get("场景")},
                {"类型": "登记场景", "区域": item.get("区域"), "场景": item.get("场景"),
                 "方位出口": copy.deepcopy(exits)},
            ]
        else:
            return _with_turn_state({"ok": False, "槽位": slot,
                                     "错误": f"{prefix} 操作须为 登记、隔离 或 重连"}, state)
        item_extra = set(item) - allowed
        if item_extra:
            return _with_turn_state({
                "ok": False, "槽位": slot,
                "错误": f"{prefix}出现非预期字段：{'、'.join(sorted(item_extra))}",
            }, state)
        if not item.get("区域") or not item.get("场景"):
            return _with_turn_state({"ok": False, "槽位": slot,
                                     "错误": f"{prefix}须指定 区域、场景"}, state)
        normalized.extend(operations)
        summaries.append({"操作": operation, "区域": item["区域"], "场景": item["场景"]})

    staged = {}
    type_staged = {}
    # 同批次登记的场景名（按区域）：出口目标可前向引用批次内任意登记项，书写顺序无关
    batch_targets = {}
    for operation in normalized:
        if operation["类型"] == "登记场景":
            batch_targets.setdefault(operation.get("区域"), set()).add(operation.get("场景"))
    validation = []
    for operation in normalized:
        if operation["类型"] == "登记场景":
            result = sc.register_scene(slot, operation, staged, type_staged,
                                        known_targets=batch_targets.get(operation.get("区域")))
        else:
            result = sc.isolate_scene(slot, operation, staged)
        validation.append(result)
        if not result.get("ok"):
            return _with_turn_state({
                "ok": False, "槽位": slot,
                "错误": "scene-prepare 场景规划预校验失败：" + result.get("msg", "未知错误"),
            }, state)

    _scene_drafts.write_batch(slot, round_number, normalized)
    remaining = [r.get("剩余配额") for r in validation if r.get("剩余配额") is not None]
    result = {"ok": True, "槽位": slot, "场景": summaries}
    if remaining:
        result["剩余配额"] = remaining[-1]
    return _with_turn_state(result, state)


def _quest_definition_summary(definition):
    nodes = definition.get("nodes") or {}
    fact_keys = set()
    for node in nodes.values():
        fact_keys.update(referenced_facts(node.get("condition")))
        fact_keys.update(referenced_facts(node.get("close_condition")))
    return {
        "名称": definition.get("name") or "",
        "节点数": len(nodes),
        "终局数": sum(1 for node in nodes.values() if node.get("terminal")),
        "扩展点数": sum(1 for node in nodes.values() if node.get("extension")),
        "关闭条件节点数": sum(
            1 for node in nodes.values() if node.get("close_condition") is not None
        ),
        "引用事实": sorted(fact_keys),
    }


def quest_prepare(payload=None):
    """批量预校验即兴任务蓝图，并以线索名称保存当前 round 最新草稿批次。"""
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        return {"ok": False, "错误": "quest-prepare stdin 须为 JSON 对象"}
    slot = payload.get("槽位")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot <= 0:
        return {"ok": False, "错误": "quest-prepare 缺少有效正式 槽位"}
    turn = _turn_state.read_state(slot)
    state = turn["state"]
    if state != _turn_state.AWAITING_JUDGE:
        result = _turn_error(
            slot,
            "quest_prepare_not_expected",
            "quest-prepare 只允许在 go 已完成、等待 judge 时调用",
            state,
        )
        result["ok"] = False
        return result

    extra = set(payload) - {"槽位", "任务"}
    if extra:
        return _with_turn_state({
            "ok": False,
            "槽位": slot,
            "错误": f"quest-prepare 出现非预期字段：{'、'.join(sorted(extra))}",
        }, state)
    items = payload.get("任务")
    if not isinstance(items, list) or not items:
        return _with_turn_state({
            "ok": False,
            "槽位": slot,
            "错误": "quest-prepare 任务 须为非空数组",
        }, state)

    world_facts = normalize_world_facts(copy.deepcopy(sm.read_world_facts(slot)))
    quest_state = normalize_quest_state(copy.deepcopy(sm.read_quest_state(slot)))
    import_legacy_quests(sm.read_explore(slot) or {}, quest_state)
    records = []
    prepared = []
    seen_names = set()

    for index, item in enumerate(items, 1):
        prefix = f"quest-prepare 第 {index} 项"
        if not isinstance(item, dict):
            return _with_turn_state({"ok": False, "槽位": slot,
                                     "错误": f"{prefix}须为对象"}, state)
        operation = item.get("操作")
        if operation == "创建":
            allowed = {"操作", "蓝图", "隐藏"}
            hidden = item.get("隐藏", False)
            if not isinstance(hidden, bool):
                return _with_turn_state({"ok": False, "槽位": slot,
                                         "错误": f"{prefix} 隐藏 须为布尔值"}, state)
            kind = "create"
        elif operation == "扩展":
            allowed = {"操作", "蓝图"}
            hidden = False
            kind = "extend"
        elif operation == "修改":
            allowed = {"操作", "蓝图"}
            hidden = False
            kind = "modify"
        elif operation == "关闭":
            allowed = {"操作", "蓝图"}
            hidden = False
            kind = "close"
        else:
            return _with_turn_state({"ok": False, "槽位": slot,
                                     "错误": f"{prefix} 操作须为 创建、扩展、修改 或 关闭"}, state)
        item_extra = set(item) - allowed
        if item_extra:
            return _with_turn_state({
                "ok": False,
                "槽位": slot,
                "错误": f"{prefix}出现非预期字段：{'、'.join(sorted(item_extra))}",
            }, state)
        raw = item.get("蓝图")
        if not isinstance(raw, dict):
            return _with_turn_state({"ok": False, "槽位": slot,
                                     "错误": f"{prefix}须传入 蓝图 对象"}, state)
        raw_name = raw.get("名称") or raw.get("name")
        normalized_name = raw_name.strip() if isinstance(raw_name, str) else None
        if normalized_name and normalized_name in seen_names:
            return _with_turn_state({"ok": False, "槽位": slot,
                                     "错误": f"任务草稿批次含重复线索名称【{normalized_name}】"}, state)
        if kind == "close":
            extra_keys = set(raw) - {"名称", "节点", "描述"}
            if extra_keys:
                return _with_turn_state({"ok": False, "槽位": slot,
                                         "错误": f"{prefix}关闭蓝图仅允许 名称/节点/描述 字段"}, state)
            if not normalized_name:
                return _with_turn_state({"ok": False, "槽位": slot,
                                         "错误": f"{prefix}关闭蓝图须提供非空 名称"}, state)
            if not isinstance(raw.get("描述"), str) or not raw["描述"].strip():
                return _with_turn_state({"ok": False, "槽位": slot,
                                         "错误": f"{prefix}关闭蓝图须提供非空 描述"}, state)
        definition = None
        try:
            if kind == "create":
                definition = create_quest(
                    world_facts, quest_state, copy.deepcopy(raw), hidden=hidden,
                    incremental=True,
                )
            elif kind == "extend":
                definition = extend_quest(world_facts, quest_state, copy.deepcopy(raw),
                                          incremental=True)
            elif kind == "close":
                validate_close_extension(quest_state, normalized_name, raw.get("节点"))
            else:
                definition = modify_quest_rewards(world_facts, quest_state, copy.deepcopy(raw))
        except (KeyError, TypeError, ValueError) as exc:
            return _with_turn_state({
                "ok": False,
                "槽位": slot,
                "错误": f"{prefix}任务蓝图预校验失败：{exc}",
            }, state)

        quest_name = definition["name"] if definition is not None else normalized_name
        if quest_name in seen_names:
            return _with_turn_state({"ok": False, "槽位": slot,
                                     "错误": f"任务草稿批次含重复线索名称【{quest_name}】"}, state)
        seen_names.add(quest_name)
        if kind == "close":
            record_version = quest_state["definitions"][quest_name]["version"]
            summary = {"线索": quest_name, "关闭节点": raw["节点"].strip(),
                       "描述": raw["描述"].strip()}
        else:
            record_version = definition["version"]
            summary = _quest_definition_summary(definition)
        records.append({
            "quest_name": quest_name,
            "kind": kind,
            "payload": copy.deepcopy(raw),
            "hidden": hidden,
            "content_hash": _quest_drafts.definition_hash(
                kind, definition if definition is not None else raw, hidden),
            "definition_version": record_version,
            "summary": copy.deepcopy(summary),
        })
        prepared.append({
            "操作": operation,
            "版本": record_version,
            **summary,
        })

    round_number = sm.read_round(slot)
    _quest_drafts.write_batch(slot, round_number, records)
    return {
        "ok": True,
        "槽位": slot,
        "任务": prepared,
        "turn_state": state,
    }


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
    if cmd == "scene-prepare":
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(json.dumps({"错误": f"scene-prepare: JSON 解析失败（{e}）"}, ensure_ascii=False, indent=2))
            return 2
        result = scene_prepare(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and result.get("错误") else 0
    if cmd == "quest-prepare":
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(json.dumps({"错误": f"quest-prepare: JSON 解析失败（{e}）"}, ensure_ascii=False, indent=2))
            return 2
        result = quest_prepare(payload)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if isinstance(result, dict) and result.get("错误") else 0
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
    print("未知命令: " + cmd + "\n可用: go / judge / check / random-event / scene-prepare / quest-prepare / query / setting / recommend / map-query", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        exit_code = _cli(sys.argv[1:])
    except JsonReadError as exc:
        print(json.dumps({"错误": str(exc), "错误代码": exc.code}, ensure_ascii=False, indent=2))
        exit_code = 2
    sys.exit(exit_code)
