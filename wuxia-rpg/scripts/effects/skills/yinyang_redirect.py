"""阴阳错位：有其他敌方时，在落账前将伤害转移给其中一人。"""
import random

EFFECT_MECHANIC = "命中后将伤害转移至另一名随机敌方（敌方仅一人时不转移）"


def _other_enemies(actor, target, characters):
    return [char for char in characters
            if char is not target
            and char.get("阵营") != actor.get("阵营")
            and char.get("气血", 0) > 0
            and not char.get("逃走")]


def on_settle(source, ctx):
    """保留按原目标防御计算出的伤害，只改写实际落账目标。"""
    event = ctx["事件"]
    if event.get("事件") != "伤害":
        return
    actor = ctx["行动者"]
    if event.get("攻击方") is not actor:
        return
    original = event.get("目标")
    others = _other_enemies(actor, original, ctx["角色列表"])
    if not others:
        return
    redirect = random.choice(others)
    event["原目标"] = original
    event["目标"] = redirect
    event["来源"] = ctx["行动"]["名称"] + "·阴阳错位"
    ctx["目标"] = redirect
