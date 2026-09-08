"""五雷天心 - 五雷天心掌：命中后对目标施加1层雷印。

敌方单体攻击。雷印为负向长效触发型状态，叠层越高触发概率越大
（详见 effects/leiyin.py）。识破类型「独立」：逐目标掷骰发动。十境时50%概率一次性施加2层雷印。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "leiyin"
EFFECT_DURATION = 10
EFFECT_TARGET = "target"

import random

from common import effect_loader as el

EXTRA_STACK_CHANCE = 0.50  # 十境时额外施加一层的概率


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    # 十境时50%概率一次性施2层：第1层延迟判定（仅累计层数），第2层按累计层数结算
    double = skill.get("_等级", 1) >= 10 and random.random() < EXTRA_STACK_CHANCE
    if double:
        target["_雷印延迟判定"] = True
        apply_status(target, "leiyin", dur)  # 第1层：累计，不掷骰
        target.pop("_雷印延迟判定", None)
    apply_status(target, "leiyin", dur)  # 末层：按累计层数掷骰判定
    # 雷印若于本次施加时叠层触发，则复用本次伤害数值请求追击（额外再落一次等量伤害）
    if target.pop("_雷印追击", False):
        return {"追击": [{"目标": target["名称"], "伤害": result.get("伤害", 0)}]}
    return None
