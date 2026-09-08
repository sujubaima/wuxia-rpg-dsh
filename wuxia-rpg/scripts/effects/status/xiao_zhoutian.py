"""小周天 - 每回合结束时回复气血上限5%与内力上限5%

心法运转所生之基线长效状态（未配运转特效的心法以小周天为占位）。
携带者每回合结束时各回复气血上限、内力上限的5%。
钩子只上报恢复事件，不直接改写气血/内力；实际回复、记录由引擎
apply_dot_events 统一处理（与回春/外伤同源）。
"""

HP_RATIO = 0.05
MP_RATIO = 0.05

from combat import battle_engine as be


def on_turn_end(char, characters):
    events = []
    name = char["名称"]
    max_hp = be.status_attr(char, "气血上限")
    if max_hp > 0:
        hp_heal = round(max_hp * HP_RATIO)
        if hp_heal > 0:
            events.append({"类型": "持续恢复", "数值": hp_heal, "来源": "小周天", "目标": name})
    max_mp = be.status_attr(char, "内力上限")
    if max_mp > 0:
        mp_heal = round(max_mp * MP_RATIO)
        if mp_heal > 0:
            events.append({"类型": "持续恢复内力", "数值": mp_heal, "来源": "小周天", "目标": name})
    return events if events else None
