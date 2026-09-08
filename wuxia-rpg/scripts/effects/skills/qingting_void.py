"""点水成空 - 蜻蜓点水势：命中后给目标施加扑空，身形轻灵致敌出手落空。需识破判定（独立）。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "miss_swing"
EFFECT_DURATION = 1
EFFECT_TARGET = "target"


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 命中后给目标施加1回合【扑空】（其回身攻击本施加者时精准×50%）。
    # 施加者由引擎闭包自动记为出招者（蜻蜓点水势使用者）；识破类型「独立」由引擎判定。
    apply_status(target, "miss_swing", 1)
    return {"目标施加状态": "miss_swing"}
