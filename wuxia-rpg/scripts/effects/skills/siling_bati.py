"""四灵护体 - 四灵剑法：命中后自身施加1层霸体（1回合），取四象神兽护身之意，攻守兼备。

识破类型「独立」：命中后逐目标经引擎识破掷骰，通过则触发。
1层霸体抵一次技能伤害并消耗；持续时长含十境「特效持续时间」加成、层数含十境「特效层数」加成。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "bati"
EFFECT_DURATION = 1
EFFECT_TARGET = "self"
EFFECT_STACKS = 1

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 1层霸体（抵一次技能伤害并消耗）；自身施加时引擎 +1 计时补偿。
    stacks = EFFECT_STACKS + el.effect_stack_bonus(skill)
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for _ in range(stacks):
        apply_status(actor, "bati", dur)
    return {"自身施加状态": "bati"}
