"""凝神棍意 - 行者棍法：命中后自身施加凝神"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "ningshen"
EFFECT_DURATION = 2
EFFECT_TARGET = "self"

def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 命中后自身施加2回合【凝神】；行者棍法十境表无"特效持续时间"加成，全等级均为2回合。
    # 自身施加时引擎会 +1 计时补偿，使其恰好撑到下一次自己回合行动后消除。
    apply_status(actor, "ningshen", 2)
    return {"自身施加状态": "ningshen"}
