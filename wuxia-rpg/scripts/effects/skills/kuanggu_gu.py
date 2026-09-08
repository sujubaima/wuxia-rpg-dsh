"""狂蛊入体 - 狂蛊鞭法：命中后对目标随机施加2种蛊毒之相（可重复），各2回合。

从畏缩/泄力/迷惑/破防/目盲/断筋六相中放随机取2个（允许重复，即可能两次同相），
各施加2回合。六相皆为可叠加的减益，随取随中、似蛊毒攻心。需识破判定（独立）。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后随机施加2种（可重复）2回合：畏缩/泄力/迷惑/破防/目盲/断筋"
EFFECT_DURATION = 2
EFFECT_TARGET = "target"

import random

from common import effect_loader as el

# 蛊毒六相：畏缩(暴击)/泄力(攻击)/迷惑(识破)/破防(防御)/目盲(精准)/断筋(速度)
GU_POOL = ["weisuo", "xieli", "mihuan", "po_fang", "dazzle", "broken_tendon"]
GU_COUNT = 2  # 随机施加种数（可重复）


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    picks = random.choices(GU_POOL, k=GU_COUNT)  # 允许重复
    for sid in picks:
        apply_status(target, sid, dur)
    return {"施加状态": list(dict.fromkeys(picks))}  # 去重保序供战报展示
