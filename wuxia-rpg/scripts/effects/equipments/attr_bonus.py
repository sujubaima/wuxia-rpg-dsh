"""平坦属性加成

params 形如 {stat: delta}，stat 可为武艺（搏击/剑法/刀法/长兵/奇门/暗器）
或二级属性（攻击力/防御力/速度/气血上限/内力上限等）。原样作为加成返回。
例：长剑 {"剑法": 1} → 装备后 剑法武艺 +1。
"""

def flat_bonuses(actor, params):
    return dict(params or {})
