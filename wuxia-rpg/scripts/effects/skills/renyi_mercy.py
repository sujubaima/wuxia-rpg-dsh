"""仁剑义剑：命中确认后施加强命，结算后施加破防。"""
from common import effect_loader as el

EFFECT_DURATION = 2
EFFECT_MECHANIC = "命中确认后先施加2回合【强命】保护本次伤害；结算后施加2回合【破防】"


def _duration(skill):
    return EFFECT_DURATION + el.effect_dur_bonus(skill)


def on_target_confirmed(source, ctx):
    """在本次伤害结算前施加强命。"""
    ctx["apply_status"](ctx["目标"], "qiangming", _duration(ctx["行动"]))


def on_target_resolved(source, ctx):
    """保持破防在目标结算后施加。"""
    ctx["apply_status"](ctx["目标"], "po_fang", _duration(ctx["行动"]))
