"""六如随机 - 六如棍法：命中后为自身随机施加六正状态之一（持续3回合）

兵法六如，其疾如风、侵掠如火、不动如山、难知如阴——命中后随机从
精妙（识破）/凝神（精准）/铁壁（防御）/强攻（攻击）/刚猛（暴击）/疾速（速度）
中择一施加 1 层，持续 3 回合。六者皆为基础值+20% 的线性可叠正向状态；
需通过识破判定。持续时长含十境「特效持续时间」加成。
"""
import random

# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_DURATION = 3
EFFECT_TARGET = "self"
EFFECT_MECHANIC = "命中后为自身随机施加一层：精妙/凝神/铁壁/强攻/刚猛/疾速（持续3回合）"

STATUS_POOL = ["insightful", "ningshen", "iron_wall", "qianggong", "gangmeng", "swift"]

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    status_id = random.choice(STATUS_POOL)
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    apply_status(actor, status_id, dur)
    return {"自身施加状态": status_id}
