"""回春剑意 - 兰阳剑法：命中后自身施加回春。需识破判定（独立，十境解锁特效）。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "huichun"
EFFECT_DURATION = 2
EFFECT_TARGET = "self"

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 命中后自身施加2回合【回春】，每层每回合恢复5%气血上限。
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    apply_status(actor, EFFECT_STATUS, dur)
    return {"自身施加状态": EFFECT_STATUS}
