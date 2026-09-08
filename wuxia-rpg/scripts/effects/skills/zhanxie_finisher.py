"""斩邪决胜 - 斩邪雌雄剑：本技能击败目标时自身时序+100，满境升至+150。"""

EFFECT_MECHANIC = "本技能将目标气血扣至0时，自身时序+100"
SEQ_PUSH = 100
SEQ_PUSH_MAX = 150


def on_damage_resolved(source, ctx):
    """最终技能伤害足以令实际受击目标气血归零时，推进自身时序。"""
    actor = ctx["行动者"]
    skill = ctx["行动"]
    event = ctx["事件"]
    if event.get("事件") != "伤害":
        return None
    if event.get("攻击方") is not actor or event.get("来源") != skill.get("名称"):
        return None

    target = event.get("目标")
    actual_damage = max(0, event.get("实际落气血", 0))
    if not target or target.get("气血", 0) <= 0 or actual_damage < target["气血"]:
        return None

    push = SEQ_PUSH_MAX if skill.get("_等级", 1) >= 10 else SEQ_PUSH
    before = actor.get("充能", 0)
    actor["充能"] = before + push
    return {"时序变化": [{
        "目标": actor["名称"],
        "变化": push,
        "原值": before,
        "新值": actor["充能"],
    }]}
