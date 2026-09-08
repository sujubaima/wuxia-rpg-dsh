"""炫目剑华 - 阴阳错剑：命中后扰乱目标眼目，使其精准下降。
基准持续1回合，可由武学等级的 特效持续时间 加成延长。需通过识破判定。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "dazzle"
EFFECT_DURATION = 1
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
    apply_status(target, "dazzle", dur)
    return {"目标施加状态": "dazzle"}
