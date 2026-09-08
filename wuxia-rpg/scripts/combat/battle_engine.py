#!/usr/bin/env python3
"""武侠RPG战斗引擎 - 接受战场状态和指令，输出结果和新状态"""
import json
import os
import sys
import random
import math

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from common import dao as dq  # 数据读写 + 角色派生统一入口（避免循环依赖）
from common import effect_loader as el  # 状态/技能/物品/装备特效脚本动态加载
from combat import ai_styles  # AI 战斗风格策略集（平衡/勇猛/谨慎），ai_decide 据角色字段分发
from common import status_manager as sm  # 状态管理（施加/清理/计时/钩子），战斗与大世界共用
from common import check as ck  # 判定掷骰（逃跑判定等）


def set_data_dir(path):
    """将数据目录重定向到 path（正式游戏用 slot 的 .data/ 工作副本）。

    委托 dao.set_data_dir 覆盖 characters/skills/buffs/items/factions 五子目录；
    effects 等引擎脚本目录不动。角色按需索引单例由 dao.set_data_dir → _invalidate 一并失效。
    未重定向时（调试模拟）保持默认 assets/data/；正式流程由 engine 按槽位注入数据目录。
    """
    dq.set_data_dir(path)


def character_path(name):
    """返回角色 JSON 路径（依据当前数据目录，可能已被 set_data_dir 重定向）。"""
    return dq.character_path(name)


# 按需索引库已下沉到 dao（SkillIndex/CharacterIndex/load_skills/load_characters），
# 此处保留别名转发，兼容既有 be.load_skills() / be.SkillIndex 等调用。
SkillIndex = dq.SkillIndex
CharacterIndex = dq.CharacterIndex
load_skills = dq.load_skills
load_characters = dq.load_characters


def load_buffs():
    """扫描 assets/data/buffs/（经 dao），合并为 {名称: buff}。"""
    return dq.load_all("状态")

def buff_name_of(status_id):
    """状态 id → 中文显示名（找不到则回退 id 本身）。转发至 status_manager。"""
    return sm.buff_name_of(status_id)


def _status_badges(char):
    """角色身上状态徽章文本列表（与 battle.py buff_label 同源）：长效【名】、限时【名】(N)。
    可叠加状态多层即多个相同元素。供 webui 状态快照实时渲染徽章。"""
    out = []
    for e in char.get("状态效果", []):
        name = f"【{buff_name_of(e['id'])}】"
        d = e.get("剩余时间", 0)
        out.append(name if d < 0 else f"{name}({d})")
    return out

def load_items():
    """扫描 assets/data/items/（经 dao），合并为 {名称: item}。"""
    return dq.load_all("物品")

def load_factions():
    """扫描 assets/data/factions/（经 dao），合并为 {名称: faction}。"""
    return dq.load_all("阵营")

def apply_xinfa_statuses(char, skills_db, characters_db=None):
    """运转心法：战斗开始时为角色施加其「运转心法」所定义的长效状态。

    心法状态以 剩余时间=-1 施加（<0 视为永久，不参与回合结算，战斗结束由
    clear_active_statuses 统一清除）。幂等：由 _心法已施展 标记保护，整场只施加一次。
    心法技能须 类型==心法 且在角色 武学 列表中，否则忽略。
    心法效果项可带 解锁等级：未达该境界则跳过（境界门控特效的通用机制）。
    """
    if char.get("_心法已施展"):
        return
    name = char.get("运转心法")
    if name:
        # 须为角色已习得的武学
        learned = {n for n, _ in dq.get_learned_skills_with_level(char)}
        skill = skills_db.get(name) if skills_db else None
        if skill and skill.get("类型") == "心法" and name in learned:
            xinfa_level = get_skill_level(char, name, characters_db)
            for eff in skill.get("心法效果", []):
                gate = eff.get("解锁等级")
                if gate and xinfa_level < gate:
                    continue  # 未达境界门控，不施加该项
                sid = eff.get("施加状态")
                if sid:
                    sm.apply_status(char, sid, -1, actor=char, source=name, source_type="心法")
    char["_心法已施展"] = True

def apply_equipment_hook(actor, hook_name, value):
    """对角色已装备物品的所有「装备效果」脚本调用 hook_name(value, params)，依次串联。

    仅调用脚本中实际定义了该钩子的特效；value 经各特效依次改写后返回
    （支持标量或元组，由调用方与脚本约定）。
    """
    for mod, params in dq._iter_equipment_effects(actor):
        fn = getattr(mod, hook_name, None)
        if callable(fn):
            value = fn(actor, value, params)
    return value

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

def damage_variance(value):
    """对伤害或治疗值施加±5%随机浮动；非正值原样返回（零威力对内武学保持 0，不被抬回 1）"""
    if value <= 0:
        return value
    factor = random.uniform(0.95, 1.05)
    return max(1, round(value * factor))


def apply_status(target, status_id, duration, actor=None, source=None, source_type=None, scene="战斗", extra=None):
    """施加状态。转发至 status_manager（状态管理已解耦，供大世界复用）。"""
    sm.apply_status(target, status_id, duration, actor=actor, source=source,
                    source_type=source_type, scene=scene, extra=extra)

def status_display_name(eff):
    """状态显示名。转发至 status_manager。"""
    return sm.status_display_name(eff)

def status_attr(char, attr_name):
    """获取角色经状态修正后的属性值。转发至 status_manager。"""
    return sm.status_attr(char, attr_name)

def status_action_blocked(char):
    """检查角色是否被状态禁止行动。转发至 status_manager。"""
    return sm.status_action_blocked(char)

def skill_available(char, skill):
    """技能是否可用：应用角色身上生效的技能过滤函数（如【封技】禁2-3品武学）。
    全部过滤函数返回 True 才可用，任一返回 False 即禁用。按角色实例区分。"""
    return all(fn(char, skill) for fn in sm.get_skill_filters(char))


def item_available(char, item):
    """物品是否可用：应用角色身上生效的物品过滤函数（如【封穴】禁用一切物品）。
    与 skill_available 同口径，全部过滤函数返回 True 才可用。按角色实例区分。"""
    return all(fn(char, item) for fn in sm.get_item_filters(char))

def status_trigger(char, hook_name, characters):
    """触发角色身上所有状态的指定钩子。转发至 status_manager。"""
    return sm.status_trigger(char, hook_name, characters)

def active_status_entries(char):
    """角色生效中的状态条目（含状态过滤，如散功禁心法源状态）。

    filter 应用逻辑归本层：取角色原始状态效果，应用其身上生效的状态过滤函数
    （散功等），过滤后的即战斗中实际生效的状态。按角色实例区分，状态移除即失效。
    """
    effs = char.get("状态效果", [])
    live_fns = sm.get_status_filters(char)
    for eff in effs:
        if all(fn(char, eff) for fn in live_fns):
            yield eff


# 注入「取生效状态」函数给 status_manager 分发器使用（保持依赖单向：sm 不 import battle）
sm.set_status_entries_provider(active_status_entries)


def status_mp_cost(char, base_cost):
    """使用技能时折算内力消耗（如虚耗令消耗翻倍）。转发至 status_manager。"""
    return sm.status_mp_cost(char, base_cost)

def _status_scripts(char):
    """遍历角色身上各状态对应的 effect 脚本模块（去重）。转发至 status_manager。"""
    return sm.status_scripts(char)


# ---------- 统一战斗阶段与结算 ----------
COMBAT_STAGES = (
    "on_action", "on_target_check", "on_target_confirmed", "on_damage_calc",
    "on_settle", "on_before_commit", "on_damage_resolved", "on_target_resolved",
)


def make_action_source(actor, data, source_type="技能特效"):
    """构造技能/物品行动特效来源；无脚本时返回None。"""
    if source_type == "物品特效":
        effect_id = data.get("物品特效")
        mod = el.load_item_effect(effect_id) if effect_id else None
    else:
        effect_id = data.get("技能特效")
        mod = el.load_skill_effect(effect_id) if effect_id else None
    if not mod:
        return None
    return {
        "类型": source_type, "持有者": actor, "数据": data, "模块": mod,
        "id": effect_id, "名称": data.get("名称", effect_id),
    }


def make_combat_context(actor, action, result, characters, target=None, event=None,
                        action_source=None, effect_triggered=True, insight=None):
    """构造统一阶段上下文；目标可在on_settle中被行动特效改写。"""
    return {
        "阶段": None, "行动者": actor, "原目标": target, "目标": target,
        "行动": action,
        "行动类型": (
            "物品"
            if (action_source and action_source.get("类型") == "物品特效")
            or (isinstance(action, dict) and "使用效果" in action)
            else "武学"
        ),
        "事件": event if event is not None else {}, "结果": result,
        "角色列表": characters, "行动来源": action_source,
        "特效发动": bool(effect_triggered), "识破": insight or {},
    }


def _snapshot_status_sources(characters):
    """快照全场生效状态；同持有者同状态ID聚合为一个来源。"""
    sources = []
    for char in characters:
        if is_in_fight(char):
            sources.extend(sm.combat_status_sources(char))
    return sources


def _refresh_status_source(source):
    """执行前刷新快照条目的存活子集；全被移除或持有者离场则跳过。"""
    owner = source["持有者"]
    if not is_in_fight(owner):
        return False
    current = list(active_status_entries(owner))
    live = [entry for entry in source.get("条目", [])
            if any(entry is now for now in current)]
    if not live:
        return False
    source["条目"] = live
    source["层数"] = len(live)
    source["数据"] = live[0]
    return True


def _source_apply_status(source, ctx):
    """按当前来源施加状态，并统一登记到阶段结果。"""
    owner = source["持有者"]
    data = source.get("数据", {})
    if source.get("类型") == "状态":
        src_name, src_type = source.get("名称") or source.get("id"), "状态"
    elif source.get("类型") == "物品特效":
        src_name, src_type = data.get("名称", source.get("名称")), "物品"
    else:
        src_name = data.get("名称", source.get("名称"))
        src_type = data.get("类型") or "武学"

    def apply(target, status_id, duration, extra=None):
        apply_status(target, status_id, duration, owner, source=src_name,
                     source_type=src_type, extra=extra)
        entry = {
            "目标": target["名称"], "id": status_id,
            "名称": buff_name_of(status_id), "持续时间": duration,
            "来源": src_name, "来源类型": src_type, "施加者": owner["名称"],
        }
        ctx["结果"].setdefault("施加状态", []).append(entry)
    return apply


def _merge_stage_result(hook_name, source, ctx, value):
    """合并钩子回报；多来源列表追加，目标确认时序补充来源。"""
    if not value:
        return
    result = ctx["结果"]
    if hook_name == "on_target_confirmed":
        sequence = []
        for event in (value if isinstance(value, list) else [value]):
            if not isinstance(event, dict):
                continue
            if "变化" not in event:
                _merge_stage_result("payload", source, ctx, event)
                continue
            if source.get("类型") == "状态":
                event["来源状态"] = source.get("id")
                event["来源名称"] = source.get("名称")
            sequence.append(event)
        if sequence:
            result.setdefault("时序变化", []).extend(sequence)
    elif isinstance(value, dict):
        payload = dict(value)
        # 部分脚本返回语义标签“施加状态”，真实条目已由apply_status登记，勿覆盖列表。
        if isinstance(result.get("施加状态"), list):
            payload.pop("施加状态", None)
        for key in ("时序变化", "移除负面", "状态转移", "追击"):
            entries = payload.pop(key, None)
            if isinstance(entries, list):
                result.setdefault(key, []).extend(entries)
        result.update(payload)


def _invoke_combat_hook(hook_name, source, ctx):
    mod = source.get("模块")
    fn = getattr(mod, hook_name, None) if mod else None
    if not callable(fn):
        return
    old_apply, old_settle = ctx.get("apply_status"), ctx.get("settle")
    ctx["来源"] = source
    ctx["apply_status"] = _source_apply_status(source, ctx)
    ctx["settle"] = lambda event: settle(ctx["角色列表"], event,
                                          ctx.get("行动来源"), ctx)
    value = fn(source, ctx)
    _merge_stage_result(hook_name, source, ctx, value)
    if old_apply is None:
        ctx.pop("apply_status", None)
    else:
        ctx["apply_status"] = old_apply
    if old_settle is None:
        ctx.pop("settle", None)
    else:
        ctx["settle"] = old_settle


def dispatch_combat_stage(hook_name, ctx, action_source=None):
    """统一阶段：当前行动特效先执行，再广播阶段开始时快照的全场状态。"""
    if hook_name not in COMBAT_STAGES:
        raise ValueError("未知战斗阶段: " + hook_name)
    ctx["阶段"] = hook_name
    ctx["行动来源"] = action_source
    status_sources = _snapshot_status_sources(ctx["角色列表"])
    if action_source and ctx.get("特效发动", True):
        _invoke_combat_hook(hook_name, action_source, ctx)
    for source in status_sources:
        if _refresh_status_source(source):
            _invoke_combat_hook(hook_name, source, ctx)
    return ctx


def clamp_pool(char, pool, characters, result, source):
    """当前值向下夹紧到有效上限（经 status_attr 含上限 buff 如【巫蛊】削减后的值）。

    上限类 buff 令上限降低时，当前值若超出新上限须夹紧，否则气血>上限非法。
    溢出部分以「持续伤害(已落账)」上报（不经 settle，故不被【七星逆脉】改写），
    与外伤流血区分。幂等：当前值 ≤ 上限时 no-op。**只下不上、不补差**——
    上限回升（buff 移除）时不回血，满足【巫蛊】「移除后上限恢复、气血不恢复」。

    pool: "气血" / "内力"；result: 本回合结算字典（可 None，仅夹紧不记录）；
    source: 溢出损血来源标注（如 "巫蛊"）。
    """
    new_cap = status_attr(char, pool + "上限")
    cur = char.get(pool, 0)
    if cur <= new_cap:
        return
    char[pool] = new_cap
    if result is not None:
        entry = {"目标": char["名称"], "数值": cur - new_cap,
                 "原值": cur, "新值": new_cap, "来源": source, "已落账": True}
        result.setdefault("持续伤害", [])
        result["持续伤害"].append(entry)
        if char["气血"] == 0 and pool == "气血":
            result["持续伤害击败"] = True


def topup_pool(char, pool, characters, result, source):
    """当前值向上补差到有效上限（供未来增益型上限 buff 的 on_apply 调用）。

    上限上升时当前值同步补上差额，否则增益无意义。本次重构未接线（无增益型上限 buff）。
    与 clamp_pool 对称：clamp 管向下夹紧、topup 管向上补差，二者各自显式调用，
    避免双向自动 reconcile 把上限回升误判为该补差。
    """
    new_cap = status_attr(char, pool + "上限")
    cur = char.get(pool, 0)
    delta = new_cap - cur
    if delta <= 0:
        return
    char[pool] = new_cap
    if result is not None:
        result.setdefault("持续恢复", [])
        result["持续恢复"].append({"目标": char["名称"], "数值": delta,
                                 "原值": cur, "新值": new_cap, "来源": source,
                                 "已落账": True})


def _settle_context(characters, event, action_source=None, ctx=None):
    """为一次落账事件派生独立上下文，避免嵌套结算污染外层阶段。"""
    target = event.get("目标") or event.get("行动者")
    if ctx is None:
        actor = event.get("攻击方") or event.get("行动者")
        return make_combat_context(actor, None, {}, characters, target, event,
                                   action_source, True)
    child = dict(ctx)
    child["事件"] = event
    child["目标"] = target
    child["行动来源"] = action_source
    return child


def commit_settle(characters, event, action_source=None, ctx=None):
    """最终保命阶段后把结算数值写入气血/内力池。"""
    stage_ctx = _settle_context(characters, event, action_source, ctx)
    dispatch_combat_stage("on_before_commit", stage_ctx, action_source)
    t = event.get("目标") or event.get("行动者")
    hp0, mp0 = t["气血"], t["内力"]
    kind = event["事件"]
    if kind == "伤害":
        event["实际落气血"] = min(hp0, max(0, event.get("落气血", 0)))
        event["实际落内力"] = min(mp0, max(0, event.get("落内力", 0)))
        dispatch_combat_stage("on_damage_resolved", stage_ctx, action_source)
        t["内力"] = max(0, mp0 - event.get("落内力", 0))
        t["气血"] = max(0, hp0 - event.get("落气血", 0))
    elif kind in ("治疗", "内力恢复"):
        t["气血"] = min(status_attr(t, "气血上限"), hp0 + event.get("落气血", 0))
        t["内力"] = min(status_attr(t, "内力上限"), mp0 + event.get("落内力", 0))
    elif kind == "消耗":
        t["内力"] = max(0, mp0 - event.get("扣内力", 0))
        t["气血"] = max(0, hp0 - event.get("扣气血", 0))
    return t["气血"] - hp0, t["内力"] - mp0


def settle(characters, event, action_source=None, ctx=None):
    """统一结算：行动特效和状态依次改写后提交，返回气血/内力差。"""
    stage_ctx = _settle_context(characters, event, action_source, ctx)
    dispatch_combat_stage("on_settle", stage_ctx, action_source)
    stage_ctx["目标"] = event.get("目标") or event.get("行动者")
    return commit_settle(characters, event, action_source, stage_ctx)


def _record_qiangming(result, event):
    """把一次结算的强命触发标记并入结果；同一行动可记录多次触发。"""
    marker = event.get("强命保命")
    if marker:
        result.setdefault("强命保命", []).append(marker)


def cost_blocked_reason(actor, cost, characters, source="武学"):
    """武学消耗支付能力检查（结算事件 dry-run，不提交）：不可支付返回「X不足」，否则 None。

    事件带「预演」标记：告知结算钩子此为支付检查而非真实支付——对消耗有概率性
    改写的钩子（七星逆脉）对预演一律按原样不改写，使检查恒按内力裁定，与真实
    支付时是否互换扣账池互不影响。"""
    event = {"事件": "消耗", "行动者": actor, "扣气血": 0, "扣内力": cost, "来源": source,
             "预演": True}
    ctx = make_combat_context(actor, None, {}, characters, actor, event)
    dispatch_combat_stage("on_settle", ctx)
    for pool in ("内力", "气血"):
        if event.get("扣" + pool, 0) > actor.get(pool, 0):
            return pool + "不足"
    return None


def pay_skill_cost(actor, cost, source, characters, result):
    """武学消耗支付：先经 cost_blocked_reason 固定按内力检查（预演事件）；放行后
    广播真实消耗事件+提交（此时钩子掷骰，可能改扣气血——气血不足者自损至力竭，
    支付即成立的技能不再二次拦截）。错误信息记 result，变化记录按实际扣账池挂载。"""
    blocked = cost_blocked_reason(actor, cost, characters, source)
    if blocked:
        result["错误"] = blocked
        return False
    event = {"事件": "消耗", "行动者": actor, "扣气血": 0, "扣内力": cost, "来源": source}
    hp0, mp0 = actor["气血"], actor["内力"]
    settle(characters, event)
    _record_qiangming(result, event)
    for pool, before in (("内力", mp0), ("气血", hp0)):
        if actor[pool] != before:
            result["行动者%s变化" % pool] = {"原值": before, "新值": actor[pool]}
    return True


def weapon_check_override(char, skill, blocked):
    """武器门禁豁免钩子：遍历状态脚本 on_weapon_check(char, skill, blocked)，
    任一返回 True 即放行（OR 语义）。blocked=True 表示当前按武器规则被禁。"""
    for mod in _status_scripts(char):
        fn = getattr(mod, "on_weapon_check", None)
        if callable(fn) and fn(char, skill, blocked):
            return True
    return False


def on_modify_cooldown(char, skill, cd):
    """冷却修正钩子：遍历状态脚本 on_modify_cooldown(char, skill, cd) 串联改写，封0。"""
    for mod in _status_scripts(char):
        fn = getattr(mod, "on_modify_cooldown", None)
        if callable(fn):
            cd = max(0, fn(char, skill, cd))
    return cd

def apply_dot_events(char, events, result, characters):
    """处理 on_turn_start/on_turn_end 钩子返回的持续事件：扣血/回血、记录、击败判定。

    - 持续伤害（外伤等流血/中毒）：{"类型":"持续伤害","数值":N,"来源":状态名,"目标":名}
      扣血并记入 result["持续伤害"]；气血归零记 result["持续伤害击败"]。
    - 持续恢复（回春等回血）：{"类型":"持续恢复","数值":N,"来源":状态名,"目标":名}
      回血（不超气血上限）并记入 result["持续恢复"]。
    - 持续恢复内力（小周天等回内）：{"类型":"持续恢复内力","数值":N,"来源":状态名,"目标":名}
      回内（不超内力上限）并记入 result["持续恢复内力"]。
    - 上限削减（巫蛊等上限类 buff）：{"类型":"上限削减","池":"气血"/"内力","来源":状态名,"目标":名}
      经 clamp_pool 夹紧当前值到有效上限，溢出记入 result["持续伤害"]（已落账，不经 settle）。
    钩子不改写气血/内力；本函数统一结算并记入 result，供战报渲染第一/三层。
    每名发生变化的角色记录原值→新值。
    """
    dots = []
    hots = []
    mp_hots = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("类型")
        if etype == "持续伤害":
            dmg = ev.get("数值", 0)
            if dmg <= 0:
                continue
            mp0 = char["内力"]
            if ev.get("已落账"):
                # 钩子已直接落账（如【巫蛊】削上限后夹紧溢出气血）：仅登记入持续伤害供渲染，不再结算
                entry = {
                    "目标": ev.get("目标", char["名称"]), "数值": dmg,
                    "原值": ev.get("原值", char["气血"]), "新值": ev.get("新值", char["气血"]),
                    "来源": ev.get("来源", ""),
                }
            else:
                before = char["气血"]
                # 结算阶段（如【七星逆脉】先折内力；【强命】在最终写账前保留1点气血）
                settle_ev = {"事件": "伤害", "攻击方": None, "目标": char,
                             "落气血": dmg, "落内力": 0, "来源": ev.get("来源", "")}
                settle(characters, settle_ev)
                _record_qiangming(result, settle_ev)
                entry = {
                    "目标": ev.get("目标", char["名称"]), "数值": before - char["气血"],
                    "原值": before, "新值": char["气血"], "来源": ev.get("来源", ""),
                }
                if char["内力"] != mp0:
                    entry["改扣内力"] = mp0 - char["内力"]
                    entry["内力原值"] = mp0
                    entry["内力新值"] = char["内力"]
            dots.append(entry)
            if char["气血"] == 0:
                result["持续伤害击败"] = True
        elif etype == "上限削减":
            # 上限类 buff（如【巫蛊】）令上限降低：夹紧当前值到有效上限，溢出报已落账损血。
            # 不经 settle（不被【七星逆脉】改写），由 clamp_pool 统一处理并登记。
            pool = ev.get("池", "气血")
            clamp_pool(char, pool, characters, result, ev.get("来源", ""))
        elif etype == "持续恢复":
            heal = ev.get("数值", 0)
            if heal <= 0:
                continue
            before = char["气血"]
            mp0 = char["内力"]
            # 结算阶段（如【七星逆脉】回血改入内力）
            g = settle(characters, {"事件": "治疗", "攻击方": None, "目标": char,
                                    "落气血": heal, "落内力": 0, "来源": ev.get("来源", "")})
            if g[0] > 0:
                hots.append({
                    "目标": ev.get("目标", char["名称"]), "数值": g[0],
                    "原值": before, "新值": char["气血"], "来源": ev.get("来源", ""),
                })
            if g[1] > 0:
                mp_hots.append({
                    "目标": ev.get("目标", char["名称"]), "数值": g[1],
                    "原值": mp0, "新值": char["内力"], "来源": ev.get("来源", ""),
                })
        elif etype == "持续恢复内力":
            heal = ev.get("数值", 0)
            if heal <= 0:
                continue
            before = char["内力"]
            hp0 = char["气血"]
            # 结算阶段（如【七星逆脉】回内改入气血）
            g = settle(characters, {"事件": "内力恢复", "攻击方": None, "目标": char,
                                    "落气血": 0, "落内力": heal, "来源": ev.get("来源", "")})
            if g[1] > 0:
                mp_hots.append({
                    "目标": ev.get("目标", char["名称"]), "数值": g[1],
                    "原值": before, "新值": char["内力"], "来源": ev.get("来源", ""),
                })
            if g[0] > 0:
                hots.append({
                    "目标": ev.get("目标", char["名称"]), "数值": g[0],
                    "原值": hp0, "新值": char["气血"], "来源": ev.get("来源", ""),
                })
    if dots:
        result["持续伤害"] = dots
    if hots:
        result["持续恢复"] = hots
    if mp_hots:
        result["持续恢复内力"] = mp_hots
    return dots


# ---------- 武学等级系统（十境） ----------
# 机制见 wuxia-rpg-mastery.md。技能类修饰键作用于有效值，角色类修饰键经修为反哺作用于武艺/二级属性。
# 三条双向对抗属性的系数：概率 = 基数 + (攻方 − 防方) × 系数
# 系数与每次触发的 payoff 成反比：闪避(满伤害)最低，暴击/识破(部分收益)较高。
DODGE_COEF = 0.4   # 闪避率：100 − (85 + (攻精准 − 防精准) × DODGE_COEF)
CRIT_COEF = 0.4    # 暴击率：15 + (攻暴 − 防暴) × CRIT_COEF
INSIGHT_COEF = 0.8 # 特效发动率：75 + (攻识破 − 对抗值) × INSIGHT_COEF

# 技能特效识破类型（权威位置为技能数据 技能特效 旁的 识破类型 字段）：
#   独立   逐目标各掷一次，对抗值=目标识破
#   全体   全技能一次，对抗值=目标识破均值
#   自对抗 全技能一次，对抗值=max(自身根骨×3×1.2−5, 0)
#   无     不判定，命中即生效
# 带技能特效而缺该字段时视为「独立」（兼容历史数据）。
INSIGHT_TYPES = ("独立", "全体", "自对抗", "无")


def _insight_type(skill):
    """读取技能特效的识破类型。取技能数据 识破类型 字段；缺省视「独立」。"""
    it = skill.get("识破类型")
    return it if it in INSIGHT_TYPES else "独立" if skill.get("技能特效") else "无"


def resolve_insight_ctx(skill, actor, targets, eff):
    """预算技能特效识破判定上下文。

    返回 ctx：
      独立/无 → {"类型": <t>}，交由 _attack_target 逐目标处理（无直接生效，独立逐目标掷骰）。
      全体/自对抗 → 一次性掷骰，ctx 携带 发动率/掷骰/发动，全技能共享。
    """
    it = _insight_type(skill)
    if it in ("独立", "无"):
        return {"类型": it}
    atk_insight = eff(actor, "识破")
    if it == "全体":
        adv = sum(eff(t, "识破") for t in targets) / len(targets) if targets else 0
    elif it == "自对抗":
        gen = actor.get("一级属性", {}).get("根骨", 0)
        adv = max(gen * 3 * 1.2 - 5, 0)
    else:
        return {"类型": "无"}
    rate = clamp(75 + (atk_insight - adv) * INSIGHT_COEF, 0, 100)
    roll = random.uniform(0, 100)
    return {"类型": it, "发动率": round(rate, 2), "掷骰": round(roll, 2), "发动": roll < rate}


def get_skill_level(char, skill_name, characters_db=None):
    """获取角色对某门武学的精进等级（默认1）。
    优先读角色自身的 武学 字段；战斗态角色通常不携带，则回退到预设库按名称查找。"""
    for entry in char.get("武学", []):
        if isinstance(entry, dict):
            if entry.get("名称") == skill_name:
                return max(1, entry.get("等级", 1))
        elif isinstance(entry, str) and entry == skill_name:
            return 1
    if characters_db:
        preset = characters_db.get(char.get("名称"))
        if preset and preset is not char:
            return get_skill_level(preset, skill_name, None)
    return 1


def get_active_skill_names(char, characters_db=None):
    """返回角色战斗中可上场的武学名称列表（供 AI 决策与玩家可用武学取用），至多 4 门。

    优先读 携带技能（经「配置技能界面」设定的主动武学）：
      - 字段存在（哪怕为空）→ 严格按其取，空则无可用武学（仅可休息）；
      - 字段缺省 → 回退到全部已习得武学（向后兼容预设 NPC 与旧存档，心法由调用方过滤）。
    末尾统一截断至 4 门（战斗携带上限）。
    """
    loadout = char.get("携带技能")
    if loadout is not None:
        names = [n for n in loadout if isinstance(n, str)]
    else:
        names = [n for n, _ in dq.get_learned_skills_with_level(char, characters_db)]
    return names[:4]


def get_battle_items(char, items_db=None):
    """返回角色战斗中可上场使用的消耗品种类列表（丹药/道具），至多 4 类。

    严格读 携带物品（经「配置技能界面」设定）；字段缺省视为未携带，战斗中无可上场消耗品。
    消耗实际从物品栏扣减，携带物品仅限定上场种类。
    """
    loadout = char.get("携带物品")
    if not loadout:
        return []
    if items_db is None:
        items_db = load_items()
    names, seen = [], set()
    for n in loadout:
        if not isinstance(n, str) or n in seen:
            continue
        # 仅收适用场合含战斗的消耗品（据「适用场合」字段；食物等仅世界的排除）
        if dq.is_battle_consumable(items_db.get(n, {})):
            seen.add(n)
            names.append(n)
    return names[:4]


def resolve_skill(skill, level):
    """按武学等级折算技能有效值，返回新dict（不修改原skill）。
    未配置 等级增益 或等级为1时，有效值与基准一致。"""
    level = max(1, level or 1)
    resolved = dict(skill)
    # 按 等级 字段筛选适用条目（兼容稠密/稀疏表），而非按下标切片
    applicable = [e for e in skill.get("等级增益", [])
                  if isinstance(e, dict) and e.get("等级", 1) <= level]
    power_bonus = 0.0
    mp_pct = 0
    cd_delta = 0
    crit_mult_bonus = 0.0
    for entry in applicable:
        eff = entry.get("效果", {})
        power_bonus += eff.get("威力倍率", 0)
        mp_pct += eff.get("内力消耗%", 0)
        cd_delta += eff.get("冷却时间", 0)
        crit_mult_bonus += eff.get("暴击倍率", 0)
    resolved["威力倍率"] = skill.get("威力倍率", 1.0) + power_bonus
    # 有消耗的技能下限 1 点；基础消耗为 0 的技能不抬下限（无耗武学如扫花诀保持 0 耗）
    base_cost = skill.get("内力消耗", 0)
    resolved["内力消耗"] = max(1, round(base_cost * (1 + mp_pct / 100))) if base_cost > 0 else 0
    resolved["冷却时间"] = max(0, skill.get("冷却时间", 0) + cd_delta)
    resolved["_暴击倍率加成"] = crit_mult_bonus
    resolved["_等级"] = level
    # 特效持续时间加成不由引擎注入，skill 特效脚本经 effect_loader
    # 自助按 _等级 折算并应用（apply 闭包不再偷偷增加持续时间）。
    # 特效门控：十境表中出现"解锁特效"时，仅当达到该等级后才保留 技能特效；
    # 未出现该键的武学不受影响，特效始终在线（向后兼容）。
    table = skill.get("等级增益", [])
    gated = any(isinstance(e, dict) and e.get("效果", {}).get("解锁特效") for e in table)
    if gated and not any(e.get("效果", {}).get("解锁特效") for e in applicable):
        resolved.pop("技能特效", None)
    return resolved


def compute_charge_rates(characters):
    """计算所有在场角色的充能速率（考虑状态效果）"""
    alive = [c for c in characters if is_in_fight(c)]
    if not alive:
        return
    max_speed = max(status_attr(c, "速度") for c in alive)
    for c in alive:
        c["充能速率"] = status_attr(c, "速度") + max_speed / 3


def tick_cooldowns_and_buffs(char):
    """角色回合开始时递减冷却和「战斗」场景状态持续时间。转发至 status_manager。"""
    return sm.tick_cooldowns_and_buffs(char)


def advance_atb(characters):
    """推进ATB时间轴，返回下一个行动者

    若已有角色时序≥100（就绪），先从中选行动者、不推进时间轴，避免就绪者的时序
    在等待期间被反复累加而一直上涨；仅当无人就绪时才 tick 一轮（所有人 +=充能速率）。
    """
    alive = [c for c in characters if is_in_fight(c)]
    if not alive:
        return None
    compute_charge_rates(characters)
    while True:
        ready = [c for c in alive if c["充能"] >= 100]
        if not ready:
            for c in alive:
                c["充能"] += c["充能速率"]
            continue
        ready.sort(key=lambda c: (-c["充能"], -status_attr(c, "速度")))
        actor = ready[0]
        actor["充能"] -= 100
        return actor


def predict_action_order(characters, count=6):
    """预测未来行动顺序（不修改实际状态）。

    预告紧随「当前行动者」之后：调用时若已有角色充能≥100（即已就绪、
    正要出招的当前角色），其这一次行动已由当前回合承担，预告前先扣
    除100，避免把当前角色重复计入未来序。"""
    alive = [c for c in characters if is_in_fight(c)]
    if not alive:
        return []
    max_speed = max(status_attr(c, "速度") for c in alive)
    charges = {c["名称"]: c["充能"] for c in alive}
    # 先消费当前已就绪者（充能最高、速度优先）这一次行动
    ready_now = [(c, charges[c["名称"]]) for c in alive if charges[c["名称"]] >= 100]
    if ready_now:
        ready_now.sort(key=lambda x: (-x[1], -status_attr(x[0], "速度")))
        charges[ready_now[0][0]["名称"]] -= 100
    rates = {c["名称"]: status_attr(c, "速度") + max_speed / 3 for c in alive}
    order = []
    for _ in range(count):
        while True:
            ready = [(c, charges[c["名称"]]) for c in alive if charges[c["名称"]] >= 100]
            if not ready:
                for c in alive:
                    charges[c["名称"]] += rates[c["名称"]]
                continue
            ready.sort(key=lambda x: (-x[1], -status_attr(x[0], "速度")))
            actor = ready[0][0]
            charges[actor["名称"]] -= 100
            order.append(actor["名称"])
            break
    return order


def _set_cooldown(actor, skill):
    """施展后设置技能冷却（+1 补偿：下回合开始时立即 tick 一次）。

    冷却修正经各状态脚本的 on_modify_cooldown 钩子串联改写（封0）；冷却为0者不设冷却。
    """
    cd = skill.get("冷却时间")
    if not cd:
        return
    cd = on_modify_cooldown(actor, skill, cd)
    if not cd:
        return
    actor.setdefault("冷却", {})[skill["名称"]] = cd + 1


def display_cooldown(char, skill):
    """展示用冷却时间：与 _set_cooldown 同口径（经 on_modify_cooldown 钩子折算，封0）。
    供玩家回合界面显示「下次冷却」预估，与实际设冷却一致。"""
    return on_modify_cooldown(char, skill, skill.get("冷却时间", 0) or 0)


def _weapon_error(actor, skill):
    """武器限制检查：符合要求返回 None，否则返回错误消息。

    武器不符时，状态脚本的 on_weapon_check 钩子可豁免（如人剑合一免剑施剑法）。
    """
    skill_type = skill.get("类型")
    if not skill_type or skill_type == "搏击":
        return None
    equip = actor.get("装备", {})
    items_db = load_items()
    weapon_types = []
    for slot in ["武器1", "武器2"]:
        w = equip.get(slot)
        if w:
            if isinstance(w, dict):
                weapon_types.append(w.get("子类型"))
            elif isinstance(w, str):
                info = items_db.get(w)
                if info:
                    weapon_types.append(info.get("子类型"))
    type_to_weapon = {"剑法": "剑", "刀法": "刀", "长兵": "长兵", "奇门": "奇门", "暗器": "暗器"}
    req = type_to_weapon.get(skill_type)
    if req and req not in weapon_types:
        if weapon_check_override(actor, skill, True):
            return None
        return f"未装备{req}类武器，无法使用{skill_type}武学"
    return None


def _shared_effect_triggered(insight_ctx):
    """行动级特效门控：独立识破没有行动级结果，不触发行动级特效。"""
    itype = (insight_ctx or {}).get("类型", "无")
    if itype == "无":
        return True
    if itype in ("全体", "自对抗"):
        return bool(insight_ctx.get("发动"))
    return False


def _resolve_target_effect(skill, actor, target, eff, insight_ctx, result):
    """目标未闪避后确定一次特效发动结果，并记录本目标识破信息。"""
    itype = (insight_ctx or {}).get("类型", "无")
    if itype == "无":
        return True, {"类型": "无", "发动": True}
    if itype == "独立":
        rate = clamp(75 + (eff(actor, "识破") - eff(target, "识破")) * INSIGHT_COEF, 0, 100)
        roll = random.uniform(0, 100)
        triggered = roll < rate
        result["特效发动率"] = round(rate, 2)
        result["特效掷骰"] = round(roll, 2)
        result["特效发动"] = triggered
        return triggered, {"类型": itype, "发动率": round(rate, 2),
                           "掷骰": round(roll, 2), "发动": triggered}
    result["特效发动率"] = insight_ctx["发动率"]
    result["特效掷骰"] = insight_ctx["掷骰"]
    result["特效发动"] = insight_ctx["发动"]
    return bool(insight_ctx["发动"]), insight_ctx


def _fire_action_stage(actor, skill, result, characters, insight_ctx, action_source):
    """出招成立后、逐目标处理前调用一次行动级阶段。"""
    ctx = make_combat_context(actor, skill, result, characters,
                              action_source=action_source,
                              effect_triggered=_shared_effect_triggered(insight_ctx),
                              insight=insight_ctx)
    dispatch_combat_stage("on_action", ctx, action_source)


def execute_action(actor, action, characters, characters_db=None):
    """执行一个指令，返回结算结果"""
    result = {"行动者": actor["名称"], "指令": action["类型"]}

    if action["类型"] == "休息":
        hp_before = actor["气血"]
        mp_before = actor["内力"]
        # 休息恢复量经 status_attr 折算（休息气血恢复/休息内力恢复 比例属性，默认 0/10%）；
        # 心疾等状态经 on_modify_attr 把比例改 0 即禁恢复。
        hp_recover = round(actor["气血上限"] * status_attr(actor, "休息气血恢复"))
        mp_recover = round(status_attr(actor, "内力上限") * status_attr(actor, "休息内力恢复"))
        # 装备特效：交由 effects/equipments 脚本的 modify_rest_recover 钩子改写（如木剑）
        hp_recover, mp_recover = apply_equipment_hook(
            actor, "modify_rest_recover", (hp_recover, mp_recover))
        # 结算阶段（on_settle 事件广播）：恢复去向可由状态改写（如【七星逆脉】互换）
        hp_gain, mp_gain = 0, 0
        if hp_recover > 0:
            g = settle(characters, {"事件": "治疗", "攻击方": None, "目标": actor,
                                    "落气血": hp_recover, "落内力": 0, "来源": "休息"})
            hp_gain += g[0]
            mp_gain += g[1]
        if mp_recover > 0:
            g = settle(characters, {"事件": "内力恢复", "攻击方": None, "目标": actor,
                                    "落气血": 0, "落内力": mp_recover, "来源": "休息"})
            hp_gain += g[0]
            mp_gain += g[1]
        result["恢复气血"] = hp_gain
        result["恢复内力"] = mp_gain
        result["气血变化"] = {"原值": hp_before, "新值": actor["气血"]}
        result["内力变化"] = {"原值": mp_before, "新值": actor["内力"]}
        return result

    # 使用物品（丹药/道具等消耗品）：回复气血/施加状态/时序变化，消耗行动者物品栏一个
    if action["类型"] == "物品":
        item = action["物品"]
        # 状态物品过滤（如【封穴】禁用一切物品）：被禁则无法使用
        if not item_available(actor, item):
            result["错误"] = f"【{actor['名称']}】被封穴，无法使用物品"
            return result
        target_name = action["目标"]
        target = next((c for c in characters if c["名称"] == target_name), None)
        if not target or not is_in_fight(target):
            result["错误"] = "目标无效或已败阵"
            return result
        # 缥缈：敌方道具投掷目标身形虚无，无法被选中（丹药治疗/增益不受影响）
        if (target["阵营"] != actor["阵营"]
                and item.get("子类型") == "道具"
                and not sm.is_targetable(target, actor, None)):
            result["错误"] = f"{target_name}缥缈虚无，无法被道具选中"
            return result
        eff = item.get("使用效果", {})
        inv = actor.get("物品")
        # 单场物品可用次数上限（开战时算好：min(初始背包数,2)），递减；归零即不可用
        avail = actor.get("物品可用次数")
        if isinstance(avail, dict) and avail.get(item["名称"], 0) <= 0:
            result["错误"] = f"【{item['名称']}】本场可用次数已用尽"
            return result
        if isinstance(inv, list) and item["名称"] in inv:
            inv.remove(item["名称"])
        if isinstance(avail, dict):
            avail[item["名称"]] = avail.get(item["名称"], 0) - 1
        result["物品"] = item["名称"]
        result["目标"] = target_name
        result["物品子类型"] = item.get("子类型")
        item_source = make_action_source(actor, item, "物品特效")
        item_ctx = make_combat_context(actor, item, result, characters, target,
                                       action_source=item_source)
        dispatch_combat_stage("on_action", item_ctx, item_source)
        item_ctx["事件"] = {"事件": "物品目标确认", "行动者": actor,
                            "目标": target, "物品": item}
        dispatch_combat_stage("on_target_confirmed", item_ctx, item_source)
        # 回复气血（丹药），结算阶段广播（【七星逆脉】等可改写去向）
        hp_heal = eff.get("回复气血")
        if hp_heal:
            hp_before = target["气血"]
            mp_before = target["内力"]
            g = settle(characters, {"事件": "治疗", "攻击方": actor, "目标": target,
                                    "落气血": hp_heal, "落内力": 0, "来源": item["名称"]},
                       item_source, item_ctx)
            result["恢复气血"] = result.get("恢复气血", 0) + g[0]
            result["恢复内力"] = result.get("恢复内力", 0) + g[1]
            result["目标气血变化"] = {"原值": hp_before, "新值": target["气血"]}
            if target["内力"] != mp_before:
                result["目标内力变化"] = {"原值": mp_before, "新值": target["内力"]}
        # 回复内力（丹药，如补气丸）：受有效内力上限夹紧（心疾削减内力上限时同样生效）；
        # 结算阶段广播（【七星逆脉】等可改写去向）
        mp_heal = eff.get("回复内力")
        if mp_heal:
            mp_before = target["内力"]
            hp_before = target["气血"]
            g = settle(characters, {"事件": "内力恢复", "攻击方": actor, "目标": target,
                                    "落气血": 0, "落内力": mp_heal, "来源": item["名称"]},
                       item_source, item_ctx)
            result["恢复内力"] = result.get("恢复内力", 0) + g[1]
            result["恢复气血"] = result.get("恢复气血", 0) + g[0]
            result["目标内力变化"] = {"原值": mp_before, "新值": target["内力"]}
            if target["气血"] != hp_before:
                result["目标气血变化"] = {"原值": hp_before, "新值": target["气血"]}
        # 施加状态（道具）
        applied = []
        st = eff.get("施加状态")
        if st:
            sid = st["id"]
            dur = st.get("回合", 1)
            stacks = max(1, int(st.get("层数", 1)))
            for _ in range(stacks):
                apply_status(target, sid, dur, actor, source=item["名称"], source_type="物品")
                applied.append({"目标": target_name, "id": sid,
                                "名称": buff_name_of(sid), "持续时间": dur})
        if applied:
            result.setdefault("施加状态", []).extend(applied)
        # 时序变化（道具，如爆竹令目标充能倒退）
        seq = eff.get("时序")
        if seq:
            seq_before = target.get("充能", 0)
            target["充能"] = seq_before + seq
            result["时序变化"] = [{"目标": target["名称"], "变化": seq,
                                   "原值": seq_before, "新值": target["充能"]}]
        # 净化（丹药，如清心露随机散去一桩非长效负面状态）
        purify = eff.get("净化")
        if purify:
            buffs_data = load_buffs()
            debuffs = [e for e in target.get("状态效果", [])
                       if e.get("场景", "战斗") == "战斗"
                       and e.get("剩余时间", 0) >= 0
                       and next((b for b in buffs_data.values() if b["id"] == e["id"]), {}).get("类型") == "负向"]
            removed = []
            for _ in range(min(int(purify), len(debuffs))):
                pick = random.choice(debuffs)
                debuffs.remove(pick)
                sm.remove_status(target, pick)
                removed.append({"目标": target_name, "id": pick["id"], "名称": buff_name_of(pick["id"])})
            result["净化状态"] = removed  # 即便为空也置位，供渲染区分「净化类丹药」
        # 削减（丹药，如保和丸令目标所有非长效负面状态剩余回合 -N）
        weaken = eff.get("削减")
        if weaken:
            buffs_data = load_buffs()
            affected = []
            for e in list(target.get("状态效果", [])):
                if e.get("场景", "战斗") != "战斗" or e.get("剩余时间", 0) < 0:
                    continue
                binfo = next((b for b in buffs_data.values() if b["id"] == e["id"]), None)
                if not binfo or binfo.get("类型") != "负向":
                    continue
                before = e["剩余时间"]
                e["剩余时间"] = before - int(weaken)
                gone = e["剩余时间"] <= 0
                if gone:
                    sm.remove_status(target, e)
                affected.append({"目标": target_name, "id": e["id"], "名称": buff_name_of(e["id"]),
                                 "原剩余": before, "新剩余": max(0, e["剩余时间"]), "失效": gone})
            result["削减状态"] = affected  # 即便为空也置位，供渲染区分
        # 延长（丹药，如百花丸令目标所有非长效正面状态剩余回合 +N）
        extend = eff.get("延长")
        if extend:
            buffs_data = load_buffs()
            affected = []
            for e in target.get("状态效果", []):
                if e.get("场景", "战斗") != "战斗" or e.get("剩余时间", 0) < 0:
                    continue
                binfo = next((b for b in buffs_data.values() if b["id"] == e["id"]), None)
                if not binfo or binfo.get("类型") != "正向":
                    continue
                before = e["剩余时间"]
                e["剩余时间"] = before + int(extend)
                affected.append({"目标": target_name, "id": e["id"], "名称": buff_name_of(e["id"]),
                                 "原剩余": before, "新剩余": e["剩余时间"]})
            result["延长状态"] = affected  # 即便为空也置位，供渲染区分
        if is_in_fight(target):
            item_ctx["事件"] = {"事件": "目标结算", "行动者": actor,
                                "目标": target, "物品": item}
            dispatch_combat_stage("on_target_resolved", item_ctx, item_source)
        return result

    # 武学攻击
    base_skill = action["技能"]
    # 状态技能过滤（如【封穴】禁用一切武学、【封技】禁特定品级）：被禁则无法使用
    if not skill_available(actor, base_skill):
        result["错误"] = f"【{actor['名称']}】武学被封禁，无法使用【{base_skill.get('名称', '')}】"
        return result
    # 按精进等级折算有效值（武学十境系统）
    skill = resolve_skill(base_skill, get_skill_level(actor, base_skill["名称"], characters_db))
    # 状态改写内力消耗（如【虚耗】令消耗翻倍）
    skill = dict(skill)
    skill["内力消耗"] = status_mp_cost(actor, skill["内力消耗"])

    # 敌方全体攻击：单独分流，对每个存活敌方各做一次独立判定
    if skill.get("目标范围") == "敌方全体":
        return _execute_aoe_attack(actor, skill, characters, result)

    target_name = action["目标"]
    target = next((c for c in characters if c["名称"] == target_name), None)
    if not target or not is_in_fight(target):
        result["错误"] = "目标无效或已败阵"
        return result
    # 「我方单体除自身」：对内即用但不可点自己（如扫花诀）
    if skill.get("目标范围") == "我方单体除自身" and target is actor:
        result["错误"] = "无法对自身使用"
        return result
    # 缥缈：敌方目标身形虚无，无法被单体武学选中（敌方全体攻击可波及）
    if target["阵营"] != actor["阵营"] and not sm.is_targetable(target, actor, skill):
        result["错误"] = f"{target_name}缥缈虚无，无法被单体武学选中"
        return result
    # 武器限制检查
    werr = _weapon_error(actor, skill)
    if werr:
        result["错误"] = werr
        return result
    # 冷却检查
    cd = actor.get("冷却", {})
    if skill["名称"] in cd:
        result["错误"] = f"技能冷却中（剩余{cd[skill['名称']]}tick）"
        return result
    # 武学消耗：结算事件广播（如【七星逆脉】改耗气血）+ 提交；支付池变化记录由支付层挂载
    if not pay_skill_cost(actor, skill["内力消耗"], skill["名称"], characters, result):
        return result

    result["技能"] = skill["名称"]
    result["目标"] = target_name

    # 设置冷却（冷却修正经各状态脚本的 on_modify_cooldown 钩子折算）
    _set_cooldown(actor, skill)

    # 战斗相关属性一律走 status_attr，使铁壁(防御)、精妙(识破)、疾速(速度)等
    # 状态修正真正进入判定（此前裸读二级属性，导致铁壁/精妙完全失效）
    def eff(c, name):
        return status_attr(c, name)

    # 单体与敌方全体共用同一套目标阶段。
    insight_ctx = resolve_insight_ctx(skill, actor, [target], eff)
    action_source = make_action_source(actor, skill)
    _fire_action_stage(actor, skill, result, characters, insight_ctx, action_source)
    cost_qiangming = list(result.get("强命保命", []))
    target_result = _attack_target(actor, skill, target, characters, eff,
                                   insight_ctx, action_source)
    result.update(target_result)
    if cost_qiangming:
        result["强命保命"] = cost_qiangming + target_result.get("强命保命", [])
    return result


def _attack_target(actor, skill, target, characters, eff, insight_ctx=None,
                   action_source=None):
    """对单一目标依次执行检查、确认、伤害、结算与目标完成阶段。"""
    res = {"目标": target["名称"]}
    ctx = make_combat_context(actor, skill, res, characters, target,
                              action_source=action_source,
                              effect_triggered=_shared_effect_triggered(insight_ctx),
                              insight=insight_ctx)

    # 治疗类技能不新增闪避/识破，直接进入目标确认与结算。
    if skill.get("类别") == "治疗":
        ctx["特效发动"] = True
        ctx["识破"] = {"类型": "无", "发动": True}
        ctx["事件"] = {"事件": "目标确认", "攻击方": actor, "目标": target, "武学": skill}
        dispatch_combat_stage("on_target_confirmed", ctx, action_source)
        hp_before, mp_before = target["气血"], target["内力"]
        primary_sum = (eff(actor, "力道") + eff(actor, "根骨")
                       + eff(actor, "内功") + eff(actor, "身法"))
        crit_rate = clamp(15 + (eff(actor, "暴击") - eff(target, "暴击")) * CRIT_COEF, 0, 100)
        crit_roll = random.uniform(0, 100)
        res["暴击率"] = round(crit_rate, 2)
        res["暴击掷骰"] = round(crit_roll, 2)
        is_crit = crit_roll < crit_rate
        res["暴击"] = is_crit
        heal = damage_variance(max(1, round(primary_sum * skill["威力倍率"] * 4)))
        if is_crit:
            crit_mult = 1.5 + skill.get("_暴击倍率加成", 0)
            heal = round(heal * crit_mult)
            res["暴击倍率"] = round(crit_mult, 2)
        event = {"事件": "治疗", "攻击方": actor, "目标": target,
                 "落气血": heal, "落内力": 0, "来源": skill["名称"]}
        hp_gain, mp_gain = settle(characters, event, action_source, ctx)
        actual = event.get("目标", target)
        ctx["目标"] = actual
        res["目标"] = actual["名称"]
        res["恢复气血"] = hp_gain
        if mp_gain:
            res["恢复内力"] = mp_gain
            res["目标内力变化"] = {"原值": mp_before, "新值": actual["内力"]}
            res["目标剩余内力"] = actual["内力"]
        res["目标剩余气血"] = actual["气血"]
        res["目标气血变化"] = {"原值": hp_before, "新值": actual["气血"]}
        if is_in_fight(actual):
            ctx["事件"] = {"事件": "目标结算", "攻击方": actor, "目标": actual,
                           "原目标": target, "武学": skill}
            dispatch_combat_stage("on_target_resolved", ctx, action_source)
        return res

    # 目标检查：行动特效可设必中，状态可改精准或直接改闪避率。
    friendly = target.get("阵营") == actor.get("阵营")
    check_event = {
        "事件": "目标检查", "攻击方": actor, "目标": target, "武学": skill,
        "攻击精准": eff(actor, "精准"), "防守精准": eff(target, "精准"),
        "闪避率": None, "必中": friendly,
    }
    ctx["事件"] = check_event
    dispatch_combat_stage("on_target_check", ctx, action_source)
    if check_event.get("必中"):
        dodge_rate = 0
    elif check_event.get("闪避率") is not None:
        dodge_rate = clamp(check_event["闪避率"], 0, 100)
    else:
        dodge_rate = clamp(
            100 - (85 + (check_event["攻击精准"] - check_event["防守精准"]) * DODGE_COEF),
            0, 100)
    dodge_roll = random.uniform(0, 100)
    res["闪避率"] = round(dodge_rate, 2)
    res["闪避掷骰"] = round(dodge_roll, 2)
    if dodge_roll < dodge_rate:
        res["闪避"] = True
        res["伤害"] = 0
        return res
    res["闪避"] = False

    # 独立识破在确认未闪避后每目标只掷一次；后续阶段复用同一结果。
    triggered, target_insight = _resolve_target_effect(
        skill, actor, target, eff, insight_ctx, res)
    ctx["特效发动"] = triggered
    ctx["识破"] = target_insight

    ctx["事件"] = {"事件": "攻击命中", "攻击方": actor, "目标": target, "武学": skill}
    dispatch_combat_stage("on_target_confirmed", ctx, action_source)

    crit_rate = clamp(15 + (eff(actor, "暴击") - eff(target, "暴击")) * CRIT_COEF, 0, 100)
    crit_roll = random.uniform(0, 100)
    res["暴击率"] = round(crit_rate, 2)
    res["暴击掷骰"] = round(crit_roll, 2)
    is_crit = crit_roll < crit_rate
    res["暴击"] = is_crit

    atk = eff(actor, "攻击力")
    dfs = eff(target, "防御力")
    skill_type = skill.get("类型")
    if skill_type:
        atk_skill = actor.get("武艺", {}).get(skill_type, 0)
        def_skill = target.get("武艺", {}).get(skill_type, 0)
        if atk_skill + def_skill > 0:
            sensitivity = 0.6
            skill_coeff = clamp(
                1 + sensitivity * (atk_skill - def_skill) / (atk_skill + def_skill), 0, 2)
        else:
            skill_coeff = 1.0
    else:
        skill_coeff = 1.0
    base_dmg = round(300 * atk / (atk + 3 * dfs) * skill["威力倍率"] * skill_coeff)
    dmg_floor = 0 if friendly else 1
    if is_crit:
        crit_bonus = skill.get("_暴击倍率加成", 0)
        crit_mult = clamp(1.2 + (atk - dfs) / (atk + dfs) * 0.8 + crit_bonus,
                          1.2, 2.0 + crit_bonus)
        final_dmg = damage_variance(max(dmg_floor, round(base_dmg * crit_mult)))
        res["暴击倍率"] = round(crit_mult, 2)
    else:
        final_dmg = damage_variance(max(dmg_floor, base_dmg))

    calc_event = {"事件": "伤害计算", "攻击方": actor, "目标": target,
                  "武学": skill, "伤害": final_dmg,
                  "增伤倍率": 1.0, "增伤来源": []}
    ctx["事件"] = calc_event
    dispatch_combat_stage("on_damage_calc", ctx, action_source)
    final_dmg = max(0, calc_event.get("伤害", 0))
    if calc_event.get("增伤倍率", 1.0) != 1.0:
        final_dmg = max(dmg_floor, round(final_dmg * calc_event["增伤倍率"]))
        res["增伤倍率"] = round(
            res.get("增伤倍率", 1.0) * calc_event["增伤倍率"], 2)
        res.setdefault("增伤来源", []).extend(calc_event.get("增伤来源", []))
    res["伤害"] = final_dmg

    settle_event = {"事件": "伤害", "攻击方": actor, "目标": target,
                    "原目标": target, "落气血": final_dmg, "落内力": 0,
                    "来源": skill["名称"]}
    hp_delta, mp_delta = settle(characters, settle_event, action_source, ctx)
    _record_qiangming(res, settle_event)
    actual = settle_event.get("目标", target)
    actual_hp_before = actual["气血"] - hp_delta
    actual_mp_before = actual["内力"] - mp_delta
    ctx["目标"] = actual
    if actual is not target:
        res["原目标"] = target["名称"]
        res["目标"] = actual["名称"]
        res["伤害转移"] = {"原目标": target["名称"], "实际目标": actual["名称"]}
    if settle_event.get("霸体抵挡"):
        res["伤害"] = 0
        res["霸体抵挡"] = settle_event["霸体抵挡"]
    elif settle_event.get("强命保命"):
        res["伤害"] = max(0, -hp_delta)
    else:
        res["伤害"] = final_dmg
    res["目标剩余气血"] = actual["气血"]
    res["目标气血变化"] = {"原值": actual_hp_before, "新值": actual["气血"]}
    if mp_delta:
        res["目标内力变化"] = {"原值": actual_mp_before, "新值": actual["内力"]}
        res["目标剩余内力"] = actual["内力"]
    if actual is not target:
        transfer = {"转移目标": actual["名称"], "伤害": res["伤害"],
                    "原值": actual_hp_before, "新值": actual["气血"],
                    "击败": actual["气血"] == 0}
        if settle_event.get("霸体抵挡"):
            transfer["霸体抵挡"] = settle_event["霸体抵挡"]
        res["转移结算"] = transfer
    if actual["气血"] == 0:
        res["击败"] = True

    if is_in_fight(actual):
        ctx["事件"] = {"事件": "目标结算", "攻击方": actor, "目标": actual,
                       "原目标": target, "武学": skill}
        dispatch_combat_stage("on_target_resolved", ctx, action_source)

    followups = res.pop("追击", None)
    if isinstance(followups, list):
        settled = []
        for followup in followups:
            follow_target = next((c for c in characters
                                  if c["名称"] == followup.get("目标")), None)
            if not follow_target or not is_in_fight(follow_target):
                continue
            damage = max(0, followup.get("伤害", 0))
            if damage <= 0:
                continue
            event = {"事件": "伤害", "攻击方": actor, "目标": follow_target,
                     "原目标": follow_target, "落气血": damage, "落内力": 0,
                     "来源": skill["名称"] + "·追击"}
            follow_ctx = make_combat_context(
                actor, skill, res, characters, follow_target, event, action_source,
                triggered, target_insight)
            hp_change, _ = settle(characters, event, action_source, follow_ctx)
            final_target = event.get("目标", follow_target)
            entry = {"目标": final_target["名称"], "伤害": max(0, -hp_change),
                     "原值": final_target["气血"] - hp_change,
                     "新值": final_target["气血"], "击败": final_target["气血"] == 0}
            if event.get("霸体抵挡"):
                entry["霸体抵挡"] = event["霸体抵挡"]
            _record_qiangming(entry, event)
            settled.append(entry)
        if settled:
            res["追击结算"] = settled
    return res


def _execute_aoe_attack(actor, skill, characters, result):
    """敌方全体攻击：对所有存活敌方各做一次独立判定，汇总到 result["目标结算"]。

    内力消耗、冷却、武器限制只结算一次；每个敌方独立闪避/暴击/受伤/中状态。
    """
    # 武器限制检查
    werr = _weapon_error(actor, skill)
    if werr:
        result["错误"] = werr
        return result
    # 冷却检查
    cd = actor.get("冷却", {})
    if skill["名称"] in cd:
        result["错误"] = f"技能冷却中（剩余{cd[skill['名称']]}tick）"
        return result
    # 武学消耗预检（结算事件 dry-run，如【七星逆脉】改耗气血按气血判定）
    blocked = cost_blocked_reason(actor, skill["内力消耗"], characters, skill["名称"])
    if blocked:
        result["错误"] = blocked
        return result
    # 目标：所有在场敌方（排除败阵/逃走）；敌方全体攻击可波及缥缈者，不按缥缈过滤
    enemies = [c for c in characters
               if c["阵营"] != actor["阵营"] and is_in_fight(c)]
    if not enemies:
        result["错误"] = "无可攻击的敌方目标"
        return result

    # 提交消耗（预检已过，必然支付成功）
    pay_skill_cost(actor, skill["内力消耗"], skill["名称"], characters, result)
    result["技能"] = skill["名称"]
    result["目标"] = "敌方全体"
    result["目标范围"] = "敌方全体"
    _set_cooldown(actor, skill)

    def eff(c, name):
        return status_attr(c, name)

    insight_ctx = resolve_insight_ctx(skill, actor, enemies, eff)
    if "发动率" in insight_ctx:  # 全体/自对抗：单次掷骰记于顶层结算，各目标共享
        result["特效发动率"] = insight_ctx["发动率"]
        result["特效掷骰"] = insight_ctx["掷骰"]
        result["特效发动"] = insight_ctx["发动"]
    action_source = make_action_source(actor, skill)
    _fire_action_stage(actor, skill, result, characters, insight_ctx, action_source)
    result["目标结算"] = [
        _attack_target(actor, skill, target, characters, eff, insight_ctx, action_source)
        for target in enemies
    ]
    # 自身效果提顶去重：目标结算阶段逐目标调用，自身类效果可能重复汇报。
    # 目标为自身的施加状态）会被重复执行/汇报。首个目标触发后状态已变，后续目标
    # 多半无对象（返回 None）；即便有重复，也只在顶层汇报一次。逐目标结算里剥离
    # 这些自身字段，移到顶层 result，与单体路径（自身效果本就在顶层）口径一致。
    self_removed = []
    self_applied = []
    seen_apply = set()
    for tr in result["目标结算"]:
        # 移除负面：自身净化，去重后提顶
        for rm in tr.pop("移除负面", None) or []:
            if not any(rm["id"] == x["id"] for x in self_removed):
                self_removed.append(rm)
        # 施加状态中目标为自身的：自施类（如缥缈），去重后提顶，不留在逐目标结算
        kept = []
        for g in tr.get("施加状态", []):
            if g.get("目标") == actor["名称"]:
                key = (g.get("id"), g.get("来源"))
                if key not in seen_apply:
                    seen_apply.add(key)
                    self_applied.append(g)
            else:
                kept.append(g)
        if kept:
            tr["施加状态"] = kept
        elif "施加状态" in tr:
            del tr["施加状态"]
    if self_removed:
        result["移除负面"] = self_removed
    if self_applied:
        # 合入顶层 施加状态（单体路径自施也走此字段），供渲染统一消费
        result.setdefault("施加状态", [])
        result["施加状态"] = (result["施加状态"] or []) + self_applied
    return result


def is_in_fight(c):
    """角色是否仍在场上（可行动/可被选为目标）：气血>0 且 非逃走。
    败阵靠气血<=0、逃走靠 c['逃走']=True 标记；两者都视为已退出战斗。"""
    return c.get("气血", 0) > 0 and not c.get("逃走")


def check_battle_end(characters):
    """检查战斗是否结束，返回胜利阵营或None。
    一方全员不在场上（败阵 或 逃走）即该方败、对方胜。"""
    teams = {}
    for c in characters:
        teams.setdefault(c["阵营"], []).append(c)
    for team, members in teams.items():
        if all(not is_in_fight(m) for m in members):
            winner = [t for t in teams if t != team]
            return winner[0] if winner else None
    return None


def attempt_escape(battle_state, player_name):
    """逃跑判定（个人结算）：仅逃跑者本人脱战，战斗继续。

    经 check.run_check 掷骰：判定方=逃跑者本人、对抗方=敌方在场者均值，对抗属性=全部
    一级属性（内功/力道/身法/根骨），基础成功率 50。掷骰/成功率仅内部计算（数字隔离）。
    成功：置 me['逃走']=True、清该角色身上的战斗状态效果（仅自己，不清全场），战斗不结束。
        若该方因此全员不在场，由调用方据 check_battle_end 判结束、对方胜。
    失败：不掷骰推进，仅原样返回战场状态；消耗回合与 AI 追击由调用方（run_step）
        扣充能并推进 auto_advance 实现。
    返回 {逃跑成功: bool, 逃跑者: name, 结算列表: [], 战场状态: state,
          战斗结束: None, 经验结算: {}}。
    """
    characters = battle_state["角色列表"]
    turn_num = battle_state.get("回合数", 0)
    me = next((c for c in characters if c["名称"] == player_name), None)
    my_side = me["阵营"] if me else None
    foes = [c["名称"] for c in characters
            if c["阵营"] != my_side and is_in_fight(c)]
    by_name = {c["名称"]: c for c in characters}
    attrs = ["内功", "力道", "身法", "根骨"]
    result = ck.run_check(attrs, [player_name], ",".join(foes), 50,
                          char_lookup=lambda nm: by_name.get(nm))
    success = result.get("结果") == "成功"
    state = {"角色列表": characters, "回合数": turn_num,
             "当前行动者": player_name,
             "状态摘要": get_battle_status(characters, player_name)}
    if not success:
        return {"逃跑成功": False, "逃跑者": player_name, "结算列表": [],
                "战场状态": state, "战斗结束": None, "经验结算": {}}
    # 成功：仅该角色逃走、清其战斗状态；战斗不结束（除非该方全员不在场，由调用方判）
    me["逃走"] = True
    clear_active_statuses([me])
    state["状态摘要"] = get_battle_status(characters)
    return {"逃跑成功": True, "逃跑者": player_name, "结算列表": [],
            "战场状态": state, "战斗结束": None, "经验结算": {}}


def surrender(battle_state, player_name):
    """认输：玩家方直接认输结束战斗，**敌方胜**，按败方结算（敌方发经验、玩家方为败方）。

    与逃跑不同：逃跑是脱战、无胜负、不发经验；认输是承认落败，敌方作为胜方
    获得经验，玩家方按「我方失败」走战后处置。不掷骰、不推进回合、不消耗充能，
    战场状态原样（仅清状态效果）。判定数字不外泄。
    返回 {认输: True, 结算列表: [], 战场状态: state,
          战斗结束: <敌方阵营>, 经验结算: {...}}。
    """
    characters = battle_state["角色列表"]
    turn_num = battle_state.get("回合数", 0)
    me = next((c for c in characters if c["名称"] == player_name), None)
    my_side = me["阵营"] if me else None
    # 敌方阵营：取首个与我方不同的阵营作为胜方
    winner = next((c["阵营"] for c in characters if c["阵营"] != my_side), None)
    clear_active_statuses(characters)
    state = {"角色列表": characters, "回合数": turn_num,
             "当前行动者": None,
             "状态摘要": get_battle_status(characters)}
    exp = compute_battle_exp(characters, winner) if winner else {}
    return {"认输": True, "结算列表": [], "战场状态": state,
            "战斗结束": winner, "经验结算": exp}


def compute_battle_exp(characters, winner):
    """战斗获胜经验结算（公式见 wuxia-rpg-exploration-rules.md「经验值获取」）。

    返回 {角色名: 经验增量}；平局/无胜方返回 {}。
    - 每个敌人经验 = (敌人一级属性之和 / 10)² × 80
    - 总经验 = Σ 各敌人经验；均分额 = 总经验 / 我方参战人数
    - 某角色获得 = 均分额 × (1 + 该角色.经验加成/100)，取整
    胜方全员（含败阵者）均得，败方不得。**逃走者不得经验**（即便在胜方）。
    """
    if not winner:
        return {}
    teams = {}
    for c in characters:
        teams.setdefault(c["阵营"], []).append(c)
    losers = [c for t, ms in teams.items() if t != winner for c in ms]
    # 胜方剔除逃走者：逃走者不参与经验结算
    winners = [c for c in teams.get(winner, []) if not c.get("逃走")]
    if not losers or not winners:
        return {}
    total = 0
    for c in losers:
        attrs = c.get("一级属性", {})
        s = sum(attrs.get(k, 0) for k in ("内功", "力道", "身法", "根骨"))
        total += (s / 10) ** 2 * 80
    share = total / len(winners)
    out = {}
    for c in winners:
        exp_bonus = c.get("二级属性", {}).get("经验加成", 0) or c.get("经验加成", 0)
        out[c["名称"]] = int(round(share * (1 + exp_bonus / 100)))
    return out


def clear_active_statuses(characters):
    """战斗结束时：移除「战斗」场景施加的状态。转发至 status_manager。"""
    sm.clear_active_statuses(characters)


def get_battle_status(characters, current_actor=None):
    """生成当前战场状态摘要"""
    status = []
    for c in characters:
        entry = {"名称": c["名称"], "阵营": c["阵营"]}
        if c.get("逃走"):
            entry["状态"] = "逃走"
        elif c["气血"] <= 0:
            entry["状态"] = "败阵"
        else:
            entry["气血"] = c["气血"]
            entry["气血上限"] = status_attr(c, "气血上限")
            entry["内力"] = c["内力"]
            entry["内力上限"] = status_attr(c, "内力上限")
            if c.get("状态效果"):
                entry["状态效果"] = c["状态效果"]
            if c.get("冷却"):
                entry["冷却"] = c["冷却"]
        status.append(entry)
    return status


def process_turn(battle_state, action, characters_db=None):
    """主入口：处理一个回合。"""
    if characters_db is None:
        characters_db = load_characters()
    characters = battle_state["角色列表"]
    turn_num = battle_state.get("回合数", 0) + 1

    for c in characters:
        c.setdefault("状态效果", [])
        c.setdefault("冷却", {})

    actor_name = battle_state.get("当前行动者")
    if actor_name:
        actor = next(c for c in characters if c["名称"] == actor_name)
    else:
        actor = advance_atb(characters)
        if not actor:
            return {"错误": "无可行动角色"}

    # 回合开始触发
    if actor.pop("_已tick", False):
        turn_start_events = []
    else:
        turn_start_events = status_trigger(actor, "on_turn_start", characters)

    # 检查是否被禁止行动
    blocked = status_action_blocked(actor)
    if blocked:
        result = {"行动者": actor["名称"], "指令": "无法行动", "原因": blocked}
    else:
        result = execute_action(actor, action, characters, characters_db)

    # 回合结束触发
    turn_end_events = status_trigger(actor, "on_turn_end", characters)
    apply_dot_events(actor, turn_end_events, result, characters)

    # 回合结束：递减冷却和状态，捕获失效状态
    expired = tick_cooldowns_and_buffs(actor)
    # 状态失效可能令上限回升/回落：夹紧当前值到有效上限（幂等安全网）。
    # cap-down debuff 失效→上限回升→no-op（不回血）；cap-up buff 失效→上限回落→夹紧。
    clamp_pool(actor, "气血", characters, result, "状态消退")
    clamp_pool(actor, "内力", characters, result, "状态消退")

    if turn_start_events:
        apply_dot_events(actor, turn_start_events, result, characters)
    if turn_start_events or turn_end_events:
        result["状态事件"] = turn_start_events + turn_end_events
    if expired:
        result["状态失效"] = expired
    winner = check_battle_end(characters)
    if winner:
        clear_active_statuses(characters)
    order = predict_action_order(characters) if not winner else []

    # 状态快照：该回合结算后每角色身上的状态徽章文本列表（含层数/剩余回合），供 webui
    # 实时渲染状态徽章——比「施加状态/状态失效」增量更精确（反映累计层数与 tick 递减后值）。
    result["状态快照"] = {c["名称"]: _status_badges(c) for c in characters}

    return {
        "结算": result,
        "战场状态": {
            "角色列表": characters,
            "回合数": turn_num,
            "当前行动者": None,
            "状态摘要": get_battle_status(characters),
        },
        "行动预告": order,
        "战斗结束": winner,
    }


def compute_available_skills(actor, skills_db, characters_db, characters):
    """计算行动者本回合可用技能（携带、未冷却、非心法、消耗可支付、武器匹配）。

    返回 [(base_skill, resolved_skill), ...]，按武学等级折算有效值后再判定，
    使精进降低的内力消耗/冷却真正生效。AI 决策与玩家可用武学展示共用此逻辑。
    可支付性按结算事件（消耗）dry-run 判定（如【七星逆脉】改耗气血时按气血判）。
    """
    char_info = characters_db.get(actor["名称"])
    learned_skills = get_active_skill_names(char_info if char_info else actor, characters_db)

    # 武器限制映射
    type_to_weapon = {"剑法": "剑", "刀法": "刀", "长兵": "长兵", "奇门": "奇门", "暗器": "暗器"}
    equip = actor.get("装备", {})
    items_db = load_items()
    weapon_types = []
    for slot in ["武器1", "武器2"]:
        w = equip.get(slot)
        if w:
            if isinstance(w, dict):
                weapon_types.append(w.get("子类型"))
            elif isinstance(w, str):
                item_info = items_db.get(w)
                if item_info:
                    weapon_types.append(item_info.get("子类型"))

    cd = actor.get("冷却", {})
    available = []  # [(base_skill, resolved_skill), ...]
    for name in learned_skills:
        if name in cd:
            continue
        base = skills_db.get(name)
        if not base:
            continue
        # 心法不可主动使用
        if base.get("类型") == "心法":
            continue
        rskill = resolve_skill(base, get_skill_level(actor, name, characters_db))
        # 状态改写内力消耗（如【虚耗】令消耗翻倍），使可用性判定与实际施法一致
        rskill = dict(rskill)
        rskill["内力消耗"] = status_mp_cost(actor, rskill["内力消耗"])
        # 消耗可支付性：结算事件 dry-run（【七星逆脉】改耗气血时按气血判定）
        if cost_blocked_reason(actor, rskill["内力消耗"], characters, rskill["名称"]):
            continue
        # 武器限制检查
        skill_type = rskill.get("类型")
        if skill_type and skill_type != "搏击":
            required_weapon = type_to_weapon.get(skill_type)
            if required_weapon and required_weapon not in weapon_types:
                continue
        # 状态技能过滤（如【封技】禁用2-3品武学）
        if not skill_available(actor, base):
            continue
        available.append((base, rskill))
    return available


def ai_decide(actor, characters, skills_db, characters_db, allow_escape=False, player_names=None):
    """AI决策：据角色「战斗风格」字段分发到对应策略（缺省=平衡）。

    可用技能过滤（冷却/心法/内力/武器）由 compute_available_skills 统一完成；
    可用物品由 get_battle_items 取（携带物品中的消耗品）。技能/物品/目标选择、休息倾向、
    逃跑/认输由各风格策略（scripts/ai_styles.py）决定——物品与技能统一走评分机制加权抽样。
    allow_escape 透传给风格策略，仅影响是否考虑逃跑。
    player_names 为玩家操控角色集合：若 actor 与玩家同阵营（我方AI队友），则禁止
    逃跑与认输——避免 AI 队友擅自脱战/认降致玩家被迫结束战斗。纯AI对战时为空，不限制。
    """
    char_info = characters_db.get(actor["名称"])
    available = compute_available_skills(actor, skills_db, characters_db, characters)
    items_db = load_items()
    inv = actor.get("物品", [])
    avail = actor.get("物品可用次数", {})
    battle_items = [{"名称": n, "数据": items_db[n]} for n in get_battle_items(actor, items_db)
                    if n in items_db and (not isinstance(inv, list) or n in inv)
                    and avail.get(n, 0) > 0]
    if not available and not battle_items:
        return {"类型": "休息"}
    # 我方AI队友：与任一玩家操控角色同阵营、且自身非玩家操控
    is_player_side_ai = False
    if player_names:
        player_sides = {c["阵营"] for c in characters if c["名称"] in player_names}
        is_player_side_ai = actor["阵营"] in player_sides and actor["名称"] not in player_names
    can_surrender = not is_player_side_ai
    if is_player_side_ai:
        allow_escape = False  # 我方AI队友禁止逃跑
    style_name = (char_info or {}).get("战斗风格") or "平衡"
    style_fn = ai_styles.STYLES.get(style_name, ai_styles.平衡)
    return style_fn(actor, characters, skills_db, characters_db, available,
                    allow_escape, can_surrender=can_surrender,
                    battle_items=battle_items)


def _state_with_escape(characters, turn_num, current_actor, allow_escape):
    """组装战场状态并携带「允许逃跑」标志（跨回合/存档保留，供 AI 决策读取）。"""
    st = {"角色列表": characters, "回合数": turn_num, "当前行动者": current_actor,
          "状态摘要": get_battle_status(characters, current_actor)}
    st["允许逃跑"] = allow_escape
    return st


def auto_advance(battle_state, player_action, player_name, player_names=None):
    """自动推进：执行玩家指令后连续推进AI回合直到再次轮到玩家或战斗结束

    player_name 为当前执行玩家指令的角色（run_step 时为 state['当前行动者']，run_init 无指令时可为 None）；
    player_names 为全部受控角色集合，命中即暂停；缺省时退化为 {player_name}（单角色兼容）。
    """
    if player_names is None:
        player_names = {player_name} if player_name else set()
    else:
        player_names = set(player_names)
    characters = battle_state["角色列表"]
    turn_num = battle_state.get("回合数", 0)
    allow_escape = battle_state.get("允许逃跑", False)
    results = []
    skills_db = load_skills()
    characters_db = load_characters()

    for c in characters:
        c.setdefault("状态效果", [])
        c.setdefault("冷却", {})
        # 战后带回的当前气血/内力（build_chars 从 .data/ 携带；预设 NPC 无此字段→None）
        carried_hp = c.get("气血")
        carried_mp = c.get("内力")
        if "二级属性" not in c:
            c["二级属性"] = dq.derive_secondary(c["一级属性"], c["极性"])
            c.setdefault("气血上限", c["二级属性"]["气血上限"])
            c.setdefault("内力上限", c["二级属性"]["内力上限"])
            c.setdefault("气血", c["气血上限"])
            c.setdefault("内力", c["内力上限"])
        # 修为反哺：武学十境的角色类增益累加到 武艺/二级属性（幂等）
        dq.apply_mastery_bonuses(c, characters_db, skills_db)
        # 装备平坦加成：武艺/二级属性 加成累加到角色（幂等）
        dq.apply_equipment_bonuses(c)
        # 携带的当前气血/内力优先：覆盖上面 setdefault 的满状态与上限同步结果，
        # 使战后残血/残内力在下一场战斗延续（仅夹到最新上限，不因上限同步而被「奶满」）
        if carried_hp is not None:
            c["气血"] = max(0, min(c["气血上限"], carried_hp))
        if carried_mp is not None:
            c["内力"] = max(0, min(c["内力上限"], carried_mp))
        # 运转心法：战斗开始施加心法长效状态（幂等）
        apply_xinfa_statuses(c, skills_db, characters_db)
        # 心法可能下调上限（如心疾下调内力上限、巫蛊下调气血上限）：施加后将当前值夹到
        # 有效上限，避免超限。初始化无 result 字典，传 None 仅夹紧不记录损血。
        clamp_pool(c, "气血", characters, None, "心法")
        clamp_pool(c, "内力", characters, None, "心法")

    # 执行玩家指令
    if player_action:
        state = {"角色列表": characters, "回合数": turn_num, "当前行动者": player_name}
        out = process_turn(state, player_action, characters_db)
        results.append(out["结算"])
        turn_num = out["战场状态"]["回合数"]
        characters = out["战场状态"]["角色列表"]
        # 玩家行动完毕，扣除行动消耗的充能
        player_char = next(c for c in characters if c["名称"] == player_name)
        player_char["充能"] -= 100
        if out["战斗结束"]:
            out["战场状态"]["允许逃跑"] = allow_escape
            return {"结算列表": results, "战场状态": out["战场状态"],
                    "行动预告": [], "战斗结束": out["战斗结束"],
                    "经验结算": compute_battle_exp(characters, out["战斗结束"])}

    # 循环推进AI回合
    for _ in range(50):  # 安全上限
        actor = advance_atb(characters)
        if not actor:
            break
        if actor["名称"] in player_names:
            # 轮到玩家，归还充能并停止
            actor["充能"] += 100
            order = predict_action_order(characters)
            return {"结算列表": results,
                    "战场状态": _state_with_escape(characters, turn_num, actor["名称"], allow_escape),
                    "行动预告": order, "战斗结束": None}

        # AI行动
        turn_num += 1
        tse = status_trigger(actor, "on_turn_start", characters)
        blocked = status_action_blocked(actor)
        if blocked:
            result = {"行动者": actor["名称"], "指令": "无法行动", "原因": blocked}
            apply_dot_events(actor, tse, result, characters)
            turn_end_events = status_trigger(actor, "on_turn_end", characters)
            apply_dot_events(actor, turn_end_events, result, characters)
            expired = tick_cooldowns_and_buffs(actor)
            if expired:
                result["状态失效"] = expired
            clamp_pool(actor, "气血", characters, result, "状态消退")
            clamp_pool(actor, "内力", characters, result, "状态消退")
            result["状态快照"] = {c["名称"]: _status_badges(c) for c in characters}
            results.append(result)
            winner = check_battle_end(characters)
            if winner:
                clear_active_statuses(characters)
                return {"结算列表": results,
                        "战场状态": _state_with_escape(characters, turn_num, None, allow_escape),
                        "行动预告": [], "战斗结束": winner,
                        "经验结算": compute_battle_exp(characters, winner)}
            continue

        action = ai_decide(actor, characters, skills_db, characters_db, allow_escape, player_names)
        atype = action.get("类型")

        # AI 认输：己方判负、对方胜（不掷骰、不推进AI后续回合）
        if atype == "认输":
            mini = {"角色列表": characters, "回合数": turn_num, "当前行动者": actor["名称"]}
            out = surrender(mini, actor["名称"])
            results.append({"行动者": actor["名称"], "指令": "认输"})
            return {"结算列表": results, "战场状态": out["战场状态"],
                    "行动预告": [], "战斗结束": out["战斗结束"],
                    "经验结算": out["经验结算"],
                    "结束方式": "认输", "结束方": actor["阵营"]}

        # AI 逃跑：掷骰判定（复用 attempt_escape，个人结算）。成功则该角色逃走、战斗继续；
        # 失败则消耗本次行动权（充能-100），结束本AI回合、战斗继续。
        if atype == "逃跑" and allow_escape:
            mini = {"角色列表": characters, "回合数": turn_num, "当前行动者": actor["名称"]}
            out = attempt_escape(mini, actor["名称"])
            if out["逃跑成功"]:
                results.append({"行动者": actor["名称"], "指令": "逃跑",
                                "逃跑成功": True, "逃跑者": actor["名称"]})
                # 该角色逃走、不结束战斗；检查是否因此一方全员不在场而结束
                winner = check_battle_end(characters)
                if winner:
                    clear_active_statuses(characters)
                    return {"结算列表": results,
                            "战场状态": _state_with_escape(characters, turn_num, None, allow_escape),
                            "行动预告": [], "战斗结束": winner,
                            "经验结算": compute_battle_exp(characters, winner)}
                continue
            results.append({"行动者": actor["名称"], "指令": "逃跑", "逃跑成功": False})
            actor["充能"] -= 100
            continue

        result = execute_action(actor, action, characters, characters_db)
        apply_dot_events(actor, tse, result, characters)
        turn_end_events = status_trigger(actor, "on_turn_end", characters)
        apply_dot_events(actor, turn_end_events, result, characters)
        expired = tick_cooldowns_and_buffs(actor)
        if expired:
            result["状态失效"] = expired
        clamp_pool(actor, "气血", characters, result, "状态消退")
        clamp_pool(actor, "内力", characters, result, "状态消退")
        result["状态快照"] = {c["名称"]: _status_badges(c) for c in characters}
        results.append(result)

        winner = check_battle_end(characters)
        if winner:
            clear_active_statuses(characters)
            return {"结算列表": results,
                    "战场状态": _state_with_escape(characters, turn_num, None, allow_escape),
                    "行动预告": [], "战斗结束": winner,
                    "经验结算": compute_battle_exp(characters, winner)}

    # 未结束也返回
    order = predict_action_order(characters)
    return {"结算列表": results,
            "战场状态": _state_with_escape(characters, turn_num, None, allow_escape),
            "行动预告": order, "战斗结束": None}


if __name__ == "__main__":
    # 单次调试入口：从命令行参数或 stdin 读取 JSON 指令，输出结算 JSON。
    # 日常战斗一律经 scripts/battle.py 驱动，此处仅供调试，不推荐直接调用。
    input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.loads(sys.stdin.read())
    if input_data.get("模式", "single") == "auto":
        out = auto_advance(input_data["战场状态"], input_data.get("玩家指令"), input_data["玩家角色"])
    else:
        out = process_turn(input_data["战场状态"], input_data["指令"])
    print(json.dumps(out, ensure_ascii=False, indent=2))