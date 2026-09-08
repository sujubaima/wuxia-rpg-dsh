"""凝神 - 精准按基础值每层+20%（可叠加）

每层增益携带者**基础精准**（二级属性原始值，已含派生+武学反哺+装备加成）
的20%；可叠加——多层经 status_attr 链式累加折算
（N 层 → 精准 = 基础值 + N×20%基础值）。增益基于基础值而非链中当前值，
故多层为加减叠加而非连乘。与【铁壁】【疾速】【刚猛】【强攻】对称同口径。
"""

RATIO = 0.2


def on_modify_attr(char, attr_name, base_value):
    if attr_name == "精准":
        base_pre = char.get("二级属性", {}).get("精准", 0)
        return round(base_value + base_pre * RATIO)
    return base_value
