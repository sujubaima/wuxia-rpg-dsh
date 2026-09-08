"""无量之力：倾泻行动者与目标的内力差额，提升本次伤害。"""

EFFECT_MECHANIC = (
    "命中后若目标内力低于使用者：使用者扣除二者内力之差，按差额提升本次伤害"
    "（十境时增伤效果提升；必发，无需识破）"
)

DIVISOR = 360
DIVISOR_MAX = 240


def _divisor(skill):
    return DIVISOR_MAX if skill.get("_等级", 1) >= 10 else DIVISOR


def on_damage_calc(source, ctx):
    """保持原有直接扣除行动者内力的语义，仅统一伤害阶段。"""
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    event = ctx["事件"]
    result = ctx["结果"]
    damage = event.get("伤害", 0)
    if damage <= 0:
        return
    actor_mp = actor.get("内力", 0)
    delta = actor_mp - target.get("内力", 0)
    if delta <= 0:
        return

    actor["内力"] = actor_mp - delta
    result["行动者内力变化"] = {
        "原值": actor_mp + skill.get("内力消耗", 0),
        "新值": actor["内力"],
    }
    bonus = round(damage * delta / _divisor(skill))
    if bonus <= 0:
        return
    mult = 1 + delta / _divisor(skill)
    event["伤害"] = damage + bonus
    result["增伤倍率"] = round(result.get("增伤倍率", 1.0) * mult, 2)
    result.setdefault("增伤来源", []).append({"状态": "无量之力", "倍率": round(mult, 2)})
    result["无量之力差额"] = delta
    result["无量之力增伤"] = bonus
