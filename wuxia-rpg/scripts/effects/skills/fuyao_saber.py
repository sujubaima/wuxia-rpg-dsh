"""扶摇刀势 - 扶摇刀法：刀意扶摇直上，命中后提振我方众人，全体加速。

命中后为我方全体角色（含自身）施加2回合【疾速】（速度+20%）。识破类型「独立」——
逐目标掷骰发动。自身持续比队友多1回合
由 apply_status 计时补偿自动处理（施加对象==当前行动者时 duration+1）。
持续时长含十境「特效持续时间」加成。

describe_skill_effect：状态类（EFFECT_TARGET=allies_self），描述由 body 的动态回合数 +
buff「效果」字段（疾速机制）拼成。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "swift"
EFFECT_DURATION = 2
EFFECT_TARGET = "allies_self"

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 为全体队友（含自身）施加2回合疾速（速度+20%）；时长含十境加成
    allies = [c for c in characters if c["阵营"] == actor["阵营"] and c["气血"] > 0]
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    for ally in allies:
        apply_status(ally, "swift", dur)
    return {"队友施加状态": "swift"}
