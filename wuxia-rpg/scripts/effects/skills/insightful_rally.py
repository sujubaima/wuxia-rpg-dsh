"""洞察激励 - 天道三垣剑：为全体队友（含自身）施加2层精妙

自身持续比队友多1回合——由 apply_status 的计时补偿自动处理
（施加对象==当前行动者时 duration+1），故此处统一传1，无需特判自身。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "insightful"
EFFECT_DURATION = 1
EFFECT_TARGET = "allies_self"
EFFECT_STACKS = 2

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    allies = [c for c in characters if c["阵营"] == actor["阵营"] and c["气血"] > 0]
    # 可叠加：对每位队友连施2层（每层独立 entry，各+基础识破20%）；持续时长含十境加成
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for ally in allies:
        for _ in range(EFFECT_STACKS):
            apply_status(ally, "insightful", dur)
    return {"队友施加状态": "insightful"}
