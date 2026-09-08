"""霜月快剑 - 霜月快剑：命中后识破通过再按 50% 概率使自身时序+100，剑出如霜月破空、出手先人一着。

识破类型「独立」：命中后逐目标经引擎识破掷骰，通过后再按 50% 概率发动。
触发时自身充能 +100，出手轮次立即提前。
"""
import random

EFFECT_MECHANIC = "命中后使自身时序+100（识破独立，通过后再按50%概率发动）"
SEQ_PUSH = 100    # 自身时序前推量
EXTRA_RATE = 0.50  # 识破通过后的二次概率门控


def on_target_resolved(source, ctx):
    """识破通过后再按 50% 概率：通过则自身充能 +100，回报时序变化事件。"""
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    if random.random() >= EXTRA_RATE:
        return None
    before = actor.get("充能", 0)
    actor["充能"] = before + SEQ_PUSH
    return {"时序变化": [{"目标": actor["名称"], "变化": SEQ_PUSH,
                          "原值": before, "新值": actor["充能"]}]}

