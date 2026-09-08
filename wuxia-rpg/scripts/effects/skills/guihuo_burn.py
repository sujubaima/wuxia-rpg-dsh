"""鬼火书 - 命中后对目标施加焚身（2回合），令其用技伤人时自承等量反噬。

命中后对目标施加【焚身】2回合——携带者本回合用技能造成的伤害，自身亦承担等量
（敌方全体技承全伤之和）。机制见 effects/status/fenshen.py 的结算/回合钩子。
持续时长含十境「特效持续时间」加成。需识破判定（独立）。

describe_skill_effect：状态施加类，描述由 EFFECT_STATUS 自动生成。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "fenshen"
EFFECT_DURATION = 2
EFFECT_TARGET = "target"
RATIO_BASE = 60   # 1-9境反伤比例%
RATIO_MAX = 100   # 10境反伤比例%

from common import effect_loader as el


def effect_brief(skill, level):
    """覆盖状态简述的括号部分：随等级反映焚身反伤比例（满境100%，余境60%）。"""
    pct = RATIO_MAX if (level or 1) >= 10 else RATIO_BASE
    return f"【焚身】（回合内使用技能造成的伤害，自身承担{pct}%（敌方全体技承全伤之和））"


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    # 鬼火书满境(10境)焚身反伤100%，1-9境60%。等级随焚身条目走，供 fenshen 钩子读。
    level = skill.get("_等级", 1)
    apply_status(target, EFFECT_STATUS, dur, extra={"武学等级": level})
    return {"施加状态": EFFECT_STATUS}
