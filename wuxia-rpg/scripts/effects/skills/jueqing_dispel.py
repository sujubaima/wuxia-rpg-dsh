"""绝情帖 - 命中后对目标施加3层破防，并催发自身3层强攻。

一帖绝情、心死色变：命中且识破成功后，破目标防御（3层破防，每层防御-20%），
同时激得自身杀性（3层强攻，每层攻击+20%基础值）。两层皆可叠加。
层数含十境「特效层数」加成、持续时长含十境「特效持续时间」加成。需识破判定（独立）。

describe_skill_effect：双状态施加类，无单一 EFFECT_STATUS，描述用 EFFECT_MECHANIC 文案。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后对目标施加3层破防、自身施加3层强攻"
EFFECT_TARGET_STATUS = "po_fang"   # 目标：破防
EFFECT_SELF_STATUS = "qianggong"   # 自身：强攻
EFFECT_DURATION = 2
EFFECT_TARGET_STACKS = 3
EFFECT_SELF_STACKS = 3

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 层数含十境「特效层数」加成（作用于目标/自身两侧）、时长含「特效持续时间」加成。
    t_stacks = EFFECT_TARGET_STACKS + el.effect_stack_bonus(skill)
    s_stacks = EFFECT_SELF_STACKS + el.effect_stack_bonus(skill)
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for _ in range(t_stacks):
        apply_status(target, EFFECT_TARGET_STATUS, dur)
    for _ in range(s_stacks):
        apply_status(actor, EFFECT_SELF_STATUS, dur)
    return None
