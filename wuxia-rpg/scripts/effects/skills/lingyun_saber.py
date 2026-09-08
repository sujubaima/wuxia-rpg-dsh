"""灵云刀法 - 乌衣门绝学：刀路高古苍凉，一刀呵壁问天、气吞四极；命中后身形缥缈、不可捉摸。

敌方单体攻击：识破「独立」逐目标掷骰。命中后自身施加【缥缈】——刀势尽处身形虚无，
无法被单体武学/道具选中。基础1回合，十境「特效持续时间」加成提升（满境2回合）。
自身施加时引擎会 +1 计时补偿，
使其恰好撑到下一次自己回合行动后消除。

describe_skill_effect：无前置机制（EFFECT_MECHANIC 空），描述由 body 的动态回合数 +
buff「效果」字段（缥缈机制）拼成，全随数据走、随等级变。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "ethereal"
EFFECT_DURATION = 1
EFFECT_TARGET = "self"

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    apply_status(actor, "ethereal", dur)
    return {"自身施加状态": "ethereal"}
