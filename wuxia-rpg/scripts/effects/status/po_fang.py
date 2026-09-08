"""破防 - 防御力按基础值每层-20%（可叠加，不低于0）

每层扣减携带者**基础防御力**（二级属性原始值，已含派生+武学反哺+装备加成）
的20%；可叠加——多层经 status_attr 链式累加折算
（N 层 → 防御力 = 基础值 − N×20%基础值）。扣减基于基础值而非链中当前值，
故多层为加减叠加而非连乘。最终防御力不低于1，叠满亦不致归零或转负。
"""

RATIO = 0.2


def on_modify_attr(char, attr_name, base_value):
    if attr_name == "防御力":
        base_def = char.get("二级属性", {}).get("防御力", 0)
        return max(1, round(base_value - base_def * RATIO))
    return base_value
