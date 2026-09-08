"""太极化劲 - 太极剑意：对目标施加2层虚耗，借力化力、耗散其内息。需识破判定（独立）。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "xuhao"
EFFECT_DURATION = 2
EFFECT_TARGET = "target"
EFFECT_STACKS = 2

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 命中后给目标施加多层【虚耗】（每层技能内力消耗+50%，可叠加）。
    # 层数含十境「特效层数」加成、持续时长含十境「特效持续时间」加成。
    stacks = EFFECT_STACKS + el.effect_stack_bonus(skill)
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for _ in range(stacks):
        apply_status(target, "xuhao", dur)
    return {"目标施加状态": "xuhao"}
