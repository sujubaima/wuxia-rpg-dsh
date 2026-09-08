"""轻灵剑意 - 越女剑法：自身施加2层疾速"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "swift"
EFFECT_DURATION = 1
EFFECT_TARGET = "self"
EFFECT_STACKS = 2

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 可叠加：连施多层（每层独立 entry，各+基础速度20%）；层数含十境「特效层数」加成、持续时长含十境加成。
    # 自身施加时引擎会 +1 计时补偿，使其撑到下一次自己回合行动后消除。
    stacks = EFFECT_STACKS + el.effect_stack_bonus(skill)
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for _ in range(stacks):
        apply_status(actor, "swift", dur)
    return {"自身施加状态": "swift"}
