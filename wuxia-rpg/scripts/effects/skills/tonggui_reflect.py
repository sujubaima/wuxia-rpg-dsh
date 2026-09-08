"""同归反伤 - 同归剑法：命中且通过识破判定后，自身获得1层反伤，持续2回合。"""

from common import effect_loader as el

EFFECT_STATUS = "reflect_damage"
EFFECT_DURATION = 2
EFFECT_TARGET = "self"
EFFECT_STACKS = 1


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    skill = ctx["行动"]
    apply_status = ctx["apply_status"]
    duration = EFFECT_DURATION + el.effect_dur_bonus(skill)
    stacks = EFFECT_STACKS + el.effect_stack_bonus(skill)
    for _ in range(stacks):
        apply_status(actor, EFFECT_STATUS, duration)
    return {"自身施加状态": EFFECT_STATUS}
