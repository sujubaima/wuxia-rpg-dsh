"""飞烟迷目 - 屯云飞烟剑：命中后对目标施加2回合扑空，烟幕障目、令其出手虚浮。

敌方全体攻击：引擎对每个命中敌方各调用一次 on_target_resolved，故每名敌各得2回合扑空。
识破类型「独立」——逐目标掷骰发动。扑空为负向状态，攻击携带者时精准按50%计算。
持续时长含十境「特效持续时间」加成。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "miss_swing"
EFFECT_DURATION = 2
EFFECT_TARGET = "target"

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    apply_status(target, "miss_swing", dur)
    return {"目标施加状态": "miss_swing"}
