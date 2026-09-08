"""反伤：受到技能伤害时，每层将实际伤害的20%返还攻击者。"""

from combat import battle_engine as be

RATIO_PER_STACK = 0.20


def on_damage_resolved(source, ctx):
    """最终伤害确定后结算反伤；反伤本身不再触发反伤。"""
    char = source["持有者"]
    event = ctx["事件"]
    if event.get("事件") != "伤害" or event.get("目标") is not char:
        return
    if event.get("反伤"):
        return
    skill = ctx.get("行动")
    if ctx.get("行动类型") != "武学" or not isinstance(skill, dict) or "威力倍率" not in skill:
        return
    attacker = event.get("攻击方")
    if not attacker or attacker is char or attacker.get("气血", 0) <= 0:
        return

    damage = max(0, event.get("实际落气血", 0))
    stacks = max(1, source.get("层数", 1))
    reflected = round(damage * RATIO_PER_STACK * stacks)
    if reflected <= 0:
        return

    hp_before, mp_before = attacker["气血"], attacker["内力"]
    reflect_event = {
        "事件": "伤害",
        "攻击方": char,
        "目标": attacker,
        "原目标": attacker,
        "落气血": reflected,
        "落内力": 0,
        "来源": "反伤",
        "反伤": True,
    }
    be.settle(ctx["角色列表"], reflect_event)

    entry = {
        "来源": "反伤",
        "目标": attacker["名称"],
        "层数": stacks,
        "伤害": max(0, hp_before - attacker["气血"]),
        "原值": hp_before,
        "新值": attacker["气血"],
        "内力原值": mp_before,
        "内力新值": attacker["内力"],
        "击败": attacker["气血"] == 0,
    }
    if reflect_event.get("霸体抵挡"):
        entry["霸体抵挡"] = reflect_event["霸体抵挡"]
    if reflect_event.get("强命保命"):
        entry["强命保命"] = [reflect_event["强命保命"]]
    return {"反伤结算": entry}
