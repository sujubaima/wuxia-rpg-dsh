"""玄门剑反 - 太乙玄门剑：命中后自身施加反击，剑路以攻代守、伺隙反制。需识破判定（独立，逐目标掷骰）。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "counter_attack"
EFFECT_DURATION = 1
EFFECT_TARGET = "self"


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 命中后自身施加1回合【反击】；识破类型「独立」由引擎在调用本钩子前判定。
    # 自身施加时引擎会 +1 计时补偿，使其恰好撑到下一次自己回合行动后消除。
    apply_status(actor, "counter_attack", 1)
    return {"自身施加状态": "counter_attack"}
