"""回春 - 每回合结束按气血上限5%持续恢复（可叠加）

携带者每回合结束时恢复气血上限5%的气血；可叠加——每层独立触发一次恢复，
由引擎汇总结算。钩子只上报恢复事件，实际回复由引擎统一处理。
"""

HOT_RATIO = 0.05

from combat import battle_engine as be


def on_turn_end(char, characters):
    max_hp = be.status_attr(char, "气血上限")
    if max_hp <= 0:
        return None
    heal = round(max_hp * HOT_RATIO)
    if heal <= 0:
        return None
    return {"类型": "持续恢复", "数值": heal, "来源": "回春", "目标": char["名称"]}
