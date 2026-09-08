"""泄力 - 攻击力按基础值每层-20%（可叠加）

每层扣减携带者**基础攻击力**（二级属性原始值，已含派生+武学反哺+装备加成）
的20%；可叠加——多层经 status_attr 链式累加折算
（N 层 → 攻击力 = 基础值 − N×20%基础值）。扣减基于基础值而非链中当前值，
故多层为加减叠加而非连乘。与【强攻】(+20%/层) 镜像对称，同【破防】【断筋】口径。
最终攻击力不低于 0。
"""

RATIO = 0.2


def on_modify_attr(char, attr_name, base_value):
    if attr_name == "攻击力":
        base_atk = char.get("二级属性", {}).get("攻击力", 0)
        return max(0, round(base_value - base_atk * RATIO))
    return base_value
