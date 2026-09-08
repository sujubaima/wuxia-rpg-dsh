"""炫目剑华 - 碧城剑法：命中后扰乱目标心神，施加迷惑（第10境加1层）

识破类型「无」：命中即触发，无需识破掷骰。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "mihuan"
EFFECT_DURATION = 2
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
    # 命中后给目标施加2层2回合【迷惑】（每层-基础识破20%，加法叠加）。
    # 识破类型「无」由引擎判定：命中即触发，无需识破掷骰。持续时长含十境加成。
    stacks = EFFECT_STACKS + el.effect_stack_bonus(skill)
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for _ in range(stacks):
        apply_status(target, "mihuan", dur)
    return {"目标施加状态": "mihuan"}
