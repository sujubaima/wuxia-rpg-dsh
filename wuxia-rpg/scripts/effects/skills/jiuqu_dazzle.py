"""九曲乱神 - 九曲拂尘功：命中后对目标施加3回合迷惑，拂丝如长江九曲、乱其心神。

敌方全体攻击：引擎对每个命中敌方各调用一次 on_target_resolved，故每名敌各得3回合迷惑。
识破类型「无」——命中即触发，无需识破掷骰。层数含十境「特效层数」加成、
持续时长含十境「特效持续时间」加成。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "mihuan"
EFFECT_DURATION = 3
EFFECT_TARGET = "target"
EFFECT_STACKS = 1

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 命中后给目标施加多层【迷惑】（每层识破-20%基础值，可叠加）。
    # 层数含十境「特效层数」加成、持续时长含十境「特效持续时间」加成。
    stacks = EFFECT_STACKS + el.effect_stack_bonus(skill)
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for _ in range(stacks):
        apply_status(target, "mihuan", dur)
    return {"目标施加状态": "mihuan"}
