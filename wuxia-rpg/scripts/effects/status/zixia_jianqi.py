"""紫霞剑气 - 剑法武学冷却时间-1（冷却为0者不受影响）

紫霞神功精进至第10境，运转时额外所生之长效状态。携带者施展剑法武学后，
其冷却时间 -1（经引擎 on_modify_cooldown 钩子折算，封0；冷却为0者本就不设冷却）。
机制经钩子实现，无需在引擎中硬编码特定状态 id。
"""


def on_modify_cooldown(char, skill, cd):
    """剑法武学冷却-1；非剑法或冷却0不变。"""
    if skill.get("类型") == "剑法" and cd > 0:
        return cd - 1
    return cd
