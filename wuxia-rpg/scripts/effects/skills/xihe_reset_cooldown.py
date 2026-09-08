"""剑动四方 - 西河剑法：重置我方全体除西河剑法外技能的冷却时间

必发，不走识破判定（技能数据 识破类型=无）。
敌方全体攻击时，引擎对每个命中敌方各调用一次 on_target_resolved；本效果幂等——
首次调用清空我方冷却，后续调用因冷却已空而无动作，仅首次返回重置记录。
"""
# 特效说明（说明生成读取）
EFFECT_MECHANIC = "命中后重置我方全体（除本武学外）的技能冷却（必发，无需识破）"

def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    self_name = skill["名称"]
    reset = []
    for c in characters:
        if c["阵营"] != actor["阵营"] or c["气血"] <= 0:
            continue
        cd = c.get("冷却", {})
        cleared = [n for n in list(cd.keys()) if n != self_name]
        for n in cleared:
            del cd[n]
        if cleared:
            reset.append({"角色": c["名称"], "技能": cleared})
    return {"重置冷却": reset} if reset else None
