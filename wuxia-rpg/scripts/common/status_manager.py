"""状态管理系统：状态施加/清理/计时 + 状态钩子机制。

从 battle_engine 解耦而来，使大世界（后续）与战斗共用同一套状态管理。所有状态相关
的施加、按场景清理、回合计时、属性修正、行动拦截、回合钩子、被攻击反制、装备/状态
钩子串联均在此；战斗专属逻辑（心法运转 apply_xinfa_statuses、武器门禁等）仍留
battle_engine，经此模块的 apply_status 等施加状态。

依赖：effect_loader（el，状态/技能/装备特效脚本加载）、dao（dq，状态数据读取）。
状态 entry 字段：id/剩余时间/场景(战斗|大世界)/来源/来源类型/施加者。
「场景」字段区分施加来源：战斗回合计时、战斗结束清理、净化/削减/延长丹药均只作用于
「战斗」场景状态；大世界施加的状态不参与战斗结算、不随战斗结束清除。
"""

import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from common import dao as dq
from common import effect_loader as el


def load_buffs():
    """扫描 assets/data/buffs/（经 dao），合并为 {名称: buff}。"""
    return dq.load_all("状态")


def buff_name_of(status_id):
    """状态 id → 中文显示名（找不到则回退 id 本身）"""
    for b in load_buffs().values():
        if b.get("id") == status_id:
            return b.get("名称", status_id)
    return status_id


def apply_status(target, status_id, duration, actor=None, source=None, source_type=None, scene="战斗", extra=None):
    """施加状态。scene 区分战斗/大世界（默认战斗）。

    extra：可选 dict，其字段并入状态条目，供该状态 effect 脚本按条目定制（如焚身记
    录施术武学等级以分级反伤比例）。不可叠加刷新时不更新已有条目（沿用首次 extra）。

    计时补偿：状态会在持有者自己回合结束时立即被 tick 一次。当且仅当施加对象 == 当前
    回合行动者时给 duration +1，使其撑到持有者下一次自己回合。长效状态（duration<0）
    不参与计时亦不补偿。例外：拥有 on_turn_end 钩子的状态（HOT/DOT）不补偿，否则会多
    触发一跳。
    """
    buff_info = next((b for b in load_buffs().values() if b["id"] == status_id), None)
    stack_mode = buff_info.get("叠加方式", "不可叠加") if buff_info else "不可叠加"
    if actor is not None and target is actor and duration >= 0:
        eff_mod = el.load_effect(status_id)
        if not (eff_mod and hasattr(eff_mod, "on_turn_end")):
            duration += 1

    entry = {"id": status_id, "剩余时间": duration, "场景": scene}
    if source:
        entry["来源"] = source
    if source_type:
        entry["来源类型"] = source_type
    if actor is not None:
        entry["施加者"] = actor["名称"]
    if extra:
        entry.update(extra)

    target.setdefault("状态效果", [])
    existing = [e for e in target["状态效果"] if e["id"] == status_id]

    if stack_mode == "不可叠加":
        if existing:
            # 已存在不重复施加，on_apply 不触发（避免即时效果重复结算）。
            # extra 字段仍并入既有条目：刷新时让施加方注入的定制字段（如封禁品级、
            # 武学等级）覆盖旧值，使「更强封禁留存」等升级语义生效。
            if extra:
                existing[0].update(extra)
            return
        target["状态效果"].append(entry)
        _fire_on_apply(target, entry)
    elif stack_mode == "可延长":
        if existing:
            old = existing[0]["剩余时间"]
            # 剩余时间<0 为长效（永久）状态，延长时取最长：长效不被有限时长覆盖
            if old < 0 or duration < 0:
                existing[0]["剩余时间"] = old if old < 0 else duration
            else:
                existing[0]["剩余时间"] = max(old, duration)
            # extra 同样并入既有条目（与不可叠加口径一致）
            if extra:
                existing[0].update(extra)
        else:
            target["状态效果"].append(entry)
            _fire_on_apply(target, entry)
    elif stack_mode == "可叠加":
        target["状态效果"].append(entry)
        _fire_on_apply(target, entry)


def _fire_on_apply(char, entry):
    """施加即时钩子：仅在状态条目首次新增（含可叠加的每次追加）时触发。

    effect 脚本可选 on_apply(char, eff)，承载施加时的即时效果或注册生命周期资源
    （如散工在此注册状态过滤函数）。刷新时长/重复施加不触发，避免重复结算。
    """
    mod = el.load_effect(entry.get("id"))
    if mod and hasattr(mod, "on_apply"):
        mod.on_apply(char, entry)


def status_display_name(eff):
    """状态显示名：心法(内功)所生之态以心法(内功)名相称，武学/物品来源的状态用状态名。

    供第一层润色与归属引用（增伤/时序反制/休息改写小注）；第三层状态获取箭头
    一律用状态名（buff_name_of），不经此函数。
    """
    if eff.get("来源类型") == "心法" and eff.get("来源"):
        return eff["来源"]
    return buff_name_of(eff["id"])


def remove_status(char, eff):
    """移除角色身上的指定状态条目（统一入口）。

    传入实际的状态条目对象（调用方都已握有该对象，按身份 is 精确移除，可叠加状态下
    同值条目不误删）。状态条目移除后其 filter 自然失效（filter 现场从 effect 工厂取，
    与状态同生命周期）。若该状态在角色身上已无残留条目，触发 effect 脚本可选的
    on_removed(char) 收尾钩子。返回是否实际移除（条目不在角色身上时返回 False）。
    """
    effs = char.get("状态效果", [])
    # 按身份(is)查找，可叠加状态下同值条目不误中
    if not any(e is eff for e in effs):
        return False
    char["状态效果"] = [e for e in effs if e is not eff]
    status_id = eff.get("id")
    # 状态在角色身上已无残留 → 触发 on_removed 收尾钩子
    if not any(e.get("id") == status_id for e in char["状态效果"]):
        mod = el.load_effect(status_id)
        if mod and hasattr(mod, "on_removed"):
            mod.on_removed(char)
    return True


def clear_active_statuses(characters):
    """战斗结束时：移除所有角色身上「战斗」场景施加的状态效果（含负数永久效果）。

    大世界施加的状态（scene="大世界"）保留——其生命周期由大世界管理，不随战斗结束清除。
    上限类削减（如心疾）经 status_attr 读接口折算，状态移除即自动失效。
    经 remove_status 统一入口移除，触发过滤钩子注销与 on_removed 收尾钩子。
    """
    for c in characters:
        for e in [x for x in c.get("状态效果", []) if x.get("场景", "战斗") == "战斗"]:
            remove_status(c, e)


def tick_cooldowns_and_buffs(char):
    """角色回合开始时递减冷却和「战斗」场景状态持续时间，返回本回合失效的状态列表。

    大世界施加的状态不参与战斗回合结算（不递减、不失效、不移除）。剩余时间为负数的
    状态视为永久/持续效果，不参与结算。
    """
    cd = char.get("冷却", {})
    for k in list(cd):
        cd[k] -= 1
    expired_cd = [k for k, v in cd.items() if v <= 0]
    for k in expired_cd:
        del cd[k]
    effs = char.get("状态效果", [])
    for e in effs:
        if e.get("场景", "战斗") == "战斗" and e.get("剩余时间", 0) >= 0:
            e["剩余时间"] -= 1
    expired = [e for e in effs if e.get("场景", "战斗") == "战斗" and e.get("剩余时间", 0) == 0]
    # 失效项经统一入口移除（触发过滤钩子注销与 on_removed 收尾钩子）
    for e in expired:
        remove_status(char, e)
    buffs_name = {}
    try:
        buffs_name = {b["id"]: b["名称"] for b in load_buffs().values()} if load_buffs() else {}
    except Exception:
        buffs_name = {}
    return [{"id": e["id"], "名称": buffs_name.get(e["id"], e["id"])} for e in expired]


# ---- 状态钩子机制 ----

# 状态过滤：effect 脚本声明 status_filter() 工厂返回 fn(carrying_char, eff) -> bool，
# 返回 False 表示该 eff 不生效（如散工禁心法源状态）。filter 不进内存注册表——
# 战斗状态每回合经 JSON 序列化/反序列化（battle_state.json），对象身份 id(char) 不保，
# 故 filter 改为「读取时现场从 effect 工厂取」，与角色身上状态条目同生命周期
# （状态在 filter 在，状态移除 filter 自然失效），跨回合/跨进程均一致。
def get_status_filters(char):
    """取本角色当前生效的状态过滤函数列表：遍历身上状态，对声明了 status_filter()
    工厂的 effect 脚本现场调工厂取 filter。按角色身上状态区分（A 的散工只过滤 A）。"""
    fns = []
    for eff in char.get("状态效果", []):
        mod = el.load_effect(eff["id"])
        if mod and hasattr(mod, "status_filter"):
            fns.append(mod.status_filter())
    return fns


def active_status_entries(char):
    """获取角色身上生效中的状态条目（统一入口）。

    默认返回角色原始状态效果（无过滤）——供 status_manager 独立使用（如大世界）。
    战斗层经 set_status_entries_provider 注入含状态过滤（散工等）的取状态函数后，
    分发器遍历的就是过滤后的生效状态。filter 应用逻辑归 battle_engine。
    """
    if _status_entries_provider is not None:
        yield from _status_entries_provider(char)
    else:
        for eff in char.get("状态效果", []):
            yield eff


_status_entries_provider = None


def set_status_entries_provider(fn):
    """注入「取生效状态」函数（由 battle_engine 调用，注入含 filter 应用的实现）。

    保持依赖单向（sm 不 import battle）：filter 应用逻辑在 battle，经此注入给 sm 分发器使用。
    """
    global _status_entries_provider
    _status_entries_provider = fn


# 技能过滤：effect 脚本声明 skill_filter(eff) 工厂返回 fn(carrying_char, skill) -> bool，
# 返回 False 表示该技能不可用（如封技禁2-3品武学）。工厂接收状态条目 eff，可据其携带的
# 自定义字段定制过滤（如满境封技的封禁品级集）。同 status_filter，不进内存注册表，
# 现场从工厂取，与角色状态同生命周期。
def get_skill_filters(char):
    """取本角色当前生效的技能过滤函数列表：遍历身上状态，对声明了 skill_filter()
    工厂的 effect 脚本现场调工厂取 filter（传入状态条目，供按条目定制）。按角色身上状态
    区分（A 的封技只影响 A）。"""
    fns = []
    for eff in char.get("状态效果", []):
        mod = el.load_effect(eff["id"])
        if mod and hasattr(mod, "skill_filter"):
            fns.append(mod.skill_filter(eff))
    return fns


# 物品过滤：与技能过滤同源——effect 脚本声明 item_filter(eff) 工厂返回
# fn(carrying_char, item) -> bool，返回 False 表示该物品不可用（如【封穴】禁用一切物品）。
# 工厂接收状态条目 eff，现场从工厂取，与角色状态同生命周期（A 的封穴只影响 A）。
def get_item_filters(char):
    """取本角色当前生效的物品过滤函数列表（与 get_skill_filters 同口径）。"""
    fns = []
    for eff in char.get("状态效果", []):
        mod = el.load_effect(eff["id"])
        if mod and hasattr(mod, "item_filter"):
            fns.append(mod.item_filter(eff))
    return fns



def _iter_hooks(char, hook_name):
    """遍历角色生效状态，yield (eff, hook_fn)——仅产出声明了 hook_name 的状态。

    钩子分发器的统一底层：消除「遍历 active_status_entries + load_effect + hasattr 判定」
    这段重复样板。各分发器基于此实现各自的返回聚合语义（链式改写/事件收集/OR 判定等）。
    """
    for eff in active_status_entries(char):
        mod = el.load_effect(eff["id"])
        fn = getattr(mod, hook_name, None) if mod else None
        if fn:
            yield eff, fn


def status_attr(char, attr_name):
    """获取角色经状态修正后的属性值。

    初始值取 `二级属性[attr_name]`（气血上限/内力上限/攻击力/防御力/速度/精准/识破/暴击
    均在其中），再经各 effects 脚本的 on_modify_attr 钩子链式改写。状态在即生效、
    移除即失效，无需手动改值/还原。
    """
    value = char["二级属性"][attr_name]
    for eff, fn in _iter_hooks(char, "on_modify_attr"):
        value = fn(char, attr_name, value)
    return value


def is_targetable(char, actor=None, skill=None):
    """角色是否可作为攻击目标：任一生效状态声明 target_filter() 返回 False 即不可选
    （如【缥缈】身形虚无，无法成为攻击目标）。默认 True（无状态/无过滤器）。

    与 get_skill_filters 同口径：遍历角色身上声明 target_filter() 工厂的状态，现场调
    工厂取过滤函数，按角色身上状态区分（A 的缥缈只过滤 A 是否可被选）。actor/skill
    供未来按攻击者/武学维度筛目标的特效使用（如「对某门派武学不可被选」），当前缥缈
    无条件返回 False 不读这两个参数。

    仅作用于攻击目标选取（单体/敌方全体），不影响治疗、物品等非攻击指向。"""
    fns = []
    for eff in char.get("状态效果", []):
        mod = el.load_effect(eff["id"])
        if mod and hasattr(mod, "target_filter"):
            fns.append(mod.target_filter())
    return all(fn(char, actor, skill) for fn in fns)


def status_action_blocked(char):
    """检查角色是否被状态禁止行动，返回原因或None"""
    for eff, fn in _iter_hooks(char, "on_action_blocked"):
        reason = fn(char)
        if reason:
            return reason
    return None


def status_trigger(char, hook_name, characters):
    """触发角色身上所有状态的指定钩子，返回事件列表。

    钩子可返回单个事件 dict 或事件列表（如小周天同时回气血与内力），列表自动展平。"""
    events = []
    for eff, fn in _iter_hooks(char, hook_name):
        ev = fn(char, characters)
        if ev:
            if isinstance(ev, list):
                events.extend(e for e in ev if isinstance(e, dict))
            else:
                events.append(ev)
    return events


def status_scripts(char):
    """遍历角色身上各状态对应的 effect 脚本模块（去重）。"""
    seen = set()
    for eff in active_status_entries(char):
        sid = eff.get("id")
        if sid in seen:
            continue
        seen.add(sid)
        mod = el.load_effect(sid)
        if mod:
            yield mod


def combat_status_sources(char):
    """按状态ID聚合角色当前生效状态，供统一战斗阶段分发。"""
    grouped = {}
    for eff in active_status_entries(char):
        grouped.setdefault(eff.get("id"), []).append(eff)
    for sid, entries in grouped.items():
        mod = el.load_effect(sid)
        if not mod:
            continue
        yield {
            "类型": "状态",
            "持有者": char,
            "数据": entries[0],
            "条目": list(entries),
            "层数": len(entries),
            "模块": mod,
            "id": sid,
            "名称": status_display_name(entries[0]),
        }


def status_mp_cost(char, base_cost):
    """使用技能时折算内力消耗：按 effect 模块去重，统计每个 effect 的状态条目数
    （层数），只调用一次 on_modify_mp_cost(char, value, stacks) 改写。
    （如【虚耗】可叠加，每层 +50%）。有消耗的技能折算后不低于1；零消耗武学保持 0。"""
    by_mod = {}
    for eff in active_status_entries(char):
        mod = el.load_effect(eff["id"])
        if mod and hasattr(mod, "on_modify_mp_cost"):
            by_mod[mod] = by_mod.get(mod, 0) + 1
    value = base_cost
    for mod, stacks in by_mod.items():
        value = mod.on_modify_mp_cost(char, value, stacks)
    return max(1, value) if base_cost > 0 else max(0, value)
