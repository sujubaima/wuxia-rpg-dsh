"""铁壁剑守 - 黄芦苦竹剑：命中后为自身施加2层铁壁，剑路以守代攻。需通过识破判定。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "iron_wall"
EFFECT_DURATION = 1
EFFECT_TARGET = "self"
EFFECT_STACKS = 2

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 可叠加：连施2层（每层独立 entry，各+基础防御力20%）；持续时长含十境加成
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for _ in range(EFFECT_STACKS):
        apply_status(actor, "iron_wall", dur)
    return {"自身施加状态": "iron_wall"}
