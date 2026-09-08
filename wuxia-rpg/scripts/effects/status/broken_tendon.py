"""断筋 - 每层速度降低基础值20%（可叠加）

每层按基础值（二级属性，已含装备与武学加成）独立扣除 20%，不按衰减后
现值连乘——三层即 -60%，五层归零式削弱。扣除基准固定读 char["二级属性"]
而非钩子传入的现值，保证可叠加状态下每层扣量一致。
"""

REDUCE_RATIO = 0.2  # 每层扣除基础值的 20%


def on_modify_attr(char, attr_name, base_value):
    if attr_name == "速度":
        base = char["二级属性"]["速度"]
        return max(1, base_value - int(base * REDUCE_RATIO))
    return base_value
