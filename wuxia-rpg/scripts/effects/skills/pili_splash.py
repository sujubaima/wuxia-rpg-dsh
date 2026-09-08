"""雷霆溅射 - 霹雳棍法：命中后25%伤害溅射至其他敌方（十境升至40%）。
棍势如雷霆霹雳，余劲外溢，波及旁观之敌。必发（识破类型=无），命中即溅射。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后25%伤害溅射至其他敌方"

SPLASH_RATIO = 0.25  # 溅射占主目标伤害的比例（基础）
SPLASH_RATIO_MAX = 0.40  # 十境溅射比例


def _splash_ratio(skill):
    """当前等级溅射比例：十境 0.40，其余 0.25。"""
    return SPLASH_RATIO_MAX if skill.get("_等级", 1) >= 10 else SPLASH_RATIO


def on_target_resolved(source, ctx):
    """命中后取主目标最终伤害的溅射比例，经「追击」机制溅射至其他在场敌方。"""
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dmg = result.get("伤害", 0)
    if dmg <= 0:
        return None
    splash = max(0, round(dmg * _splash_ratio(skill)))
    if splash <= 0:
        return None
    # 其他在场敌方（排除主目标、败阵、逃走）
    others = [c for c in characters
              if c is not target
              and c.get("阵营") != actor.get("阵营")
              and c.get("气血", 0) > 0
              and not c.get("逃走")]
    if not others:
        return None
    return {"追击": [{"目标": c["名称"], "伤害": splash} for c in others]}
