"""獒口霸体 - 打狗棒法：出招后自身施加2层霸体，棒势沉雄、稳如磐石。
需识破判定（全体，全技能一次掷骰共享）。出招即触发、与命中目标数无关——
走 on_action 钩子（出招成功后、逐目标结算前调一次），避免敌方全体下逐目标累乘层数。
层数含十境「特效层数」加成，持续时长含十境「特效持续时间」加成。"""
# 特效说明（说明生成读取，与 on_action 同源）
EFFECT_STATUS = "bati"
EFFECT_DURATION = 2
EFFECT_TARGET = "self"
EFFECT_STACKS = 2

from common import effect_loader as el


def on_action(source, ctx):
    actor = ctx["行动者"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 出招后自身施加多层【霸体】（每层各抵挡一次技能伤害并消耗，2层即挡2次）。
    # 层数含十境「特效层数」加成、持续时长含十境「特效持续时间」加成。
    # 自身施加时引擎会 +1 计时补偿，使其撑到下一次自己回合行动后消除。
    stacks = EFFECT_STACKS + el.effect_stack_bonus(skill)
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for _ in range(stacks):
        apply_status(actor, "bati", dur)
    return {"自身施加状态": "bati"}
