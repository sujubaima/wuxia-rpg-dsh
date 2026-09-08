"""疾速 - 速度按基础值每层+20%（可叠加）

每层增益携带者**基础速度**（二级属性原始值，已含派生+武学反哺+装备加成）
的20%；可叠加——多层经 status_attr 链式累加折算
（N 层 → 速度 = 基础值 + N×20%基础值）。增益基于基础值而非链中当前值，
故多层为加减叠加而非连乘。与【铁壁】【精妙】【破防】对称同口径。
"""

RATIO = 0.2


def on_modify_attr(char, attr_name, base_value):
    if attr_name == "速度":
        base_spd = char.get("二级属性", {}).get("速度", 0)
        return round(base_value + base_spd * RATIO)
    return base_value
