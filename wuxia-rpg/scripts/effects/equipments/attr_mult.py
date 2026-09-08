"""百分比属性加成

按角色二级属性当前值的百分比折算成平坦加成（再由 apply_equipment_bonuses 施加）。
params = {stat: 百分数}（如 10 表示 +10%），stat 为二级属性（内力上限/气血上限/攻击力 等）。
例：湛卢 {"内力上限": 10} → 内力上限 +10%（当前内力同步等量增加，不超过新上限）。
"""

def flat_bonuses(actor, params):
    sec = actor.get("二级属性", {})
    out = {}
    for stat, pct in (params or {}).items():
        base = sec.get(stat, 0)
        if base:
            out[stat] = round(base * pct / 100)
    return out
