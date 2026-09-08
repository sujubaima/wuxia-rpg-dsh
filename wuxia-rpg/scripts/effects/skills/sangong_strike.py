"""散功一击 - 通天七剑：对目标施加散功（第10境加成后 3 回合）"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "sangong"
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
    apply_status(target, "sangong", dur)
    return {"施加状态": "sangong"}
