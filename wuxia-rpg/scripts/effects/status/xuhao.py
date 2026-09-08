"""虚耗 - 携带者使用技能时内力消耗每层 +50%（可叠加）

经 status_manager.status_mp_cost 在施法前折算内力消耗：resolve_skill 算出基准消耗后，
由 on_modify_mp_cost(char, base_cost, stacks) 钩子改写。status_mp_cost 按 effect 去重
统计层数后只调用一次，故 N 层 = base × (1 + 0.5×N)（加法叠加，非连乘）。
status_mp_cost 封底不低于1，故即便折算亦不致为0。
"""

COST_ADD_PER_STACK = 0.5  # 每层 +50%


def on_modify_mp_cost(char, base_cost, stacks=1):
    return base_cost * (1 + COST_ADD_PER_STACK * stacks)
