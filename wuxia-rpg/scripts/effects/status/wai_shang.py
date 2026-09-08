"""外伤 - 每回合结束前按气血上限5%持续流血（可叠加）

碎骨拳等武学所致之外伤。携带者每回合结束前流失气血上限5%的气血；
可叠加——每层独立触发一次扣血，由引擎汇总结算。
钩子只上报伤害事件，不直接改写气血；实际扣血、记录与击败判定由引擎
apply_dot_events 完成（单一改动源）。
"""

DOT_RATIO = 0.05  # 气血上限的 5%

from combat import battle_engine as be


def on_turn_end(char, characters):
    max_hp = be.status_attr(char, "气血上限")
    if max_hp <= 0:
        return None
    dmg = round(max_hp * DOT_RATIO)
    if dmg <= 0:
        return None
    return {"类型": "持续伤害", "数值": dmg, "来源": "外伤", "目标": char["名称"]}
