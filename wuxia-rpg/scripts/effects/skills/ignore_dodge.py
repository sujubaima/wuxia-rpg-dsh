"""无视闪避：必定命中。"""
EFFECT_MECHANIC = "必定命中，无视闪避"


def on_target_check(source, ctx):
    ctx["事件"]["必中"] = True
