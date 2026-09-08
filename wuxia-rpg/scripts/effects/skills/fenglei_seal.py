"""风雷十段 - 命中后对目标施加封穴（1回合），令其无法使用武学及物品。

敌方全体攻击：引擎对每个命中敌方各调用一次 on_target_resolved（识破「独立」逐目标掷骰发动）。
命中且识破成功后，对目标施加【封穴】1回合——
携带者无法使用武学及物品（机制见 effects/status/fengxue.py 的 filter 工厂）。
持续时长含十境「特效持续时间」加成。

describe_skill_effect：状态施加类，描述由 EFFECT_STATUS 自动生成。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "fengxue"
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
    apply_status(target, EFFECT_STATUS, dur)
    return {"施加状态": EFFECT_STATUS}
