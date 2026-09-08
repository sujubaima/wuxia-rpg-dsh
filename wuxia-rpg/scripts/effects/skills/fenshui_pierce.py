"""分水破甲 - 分水刺：命中后给目标施加2层破防，刺透其护身防御。需识破判定（独立）。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "po_fang"
EFFECT_DURATION = 1
EFFECT_TARGET = "target"
EFFECT_STACKS = 2


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 命中后给目标施加2层1回合【破防】（每层-基础防御力20%，加法叠加）。
    # 施加者由引擎闭包自动记为出招者；识破类型「独立」由引擎判定。
    for _ in range(EFFECT_STACKS):
        apply_status(target, "po_fang", 1)
    return {"目标施加状态": "po_fang"}
