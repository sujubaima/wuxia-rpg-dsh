"""迷惑 - 识破按基础值每层-20%（可叠加）

每层扣减携带者**基础识破**（二级属性原始值，已含武学反哺与装备加成，不含状态修正）
的20%；可叠加——多层经 status_attr 链式累加折算
（N 层 → 识破 = 基础值 − N×20%基础值）。扣减基于基础值而非链中当前值，
故多层为加减叠加而非连乘。与破防同源。
"""

RATIO = 0.2


def on_modify_attr(char, attr_name, base_value):
    if attr_name == "识破":
        base_insight = char.get("二级属性", {}).get("识破", 0)
        return max(0, round(base_value - base_insight * RATIO))
    return base_value
