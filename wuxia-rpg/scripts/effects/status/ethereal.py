"""缥缈 - 无法被单体武学或敌方道具选中

携带者不能成为单体攻击或敌方投掷道具的目标；敌方全体攻击仍会波及。
治疗和友方增益不受影响。target_filter 随状态条目即时生效，移除后自然失效。
"""


def target_filter():
    """返回目标过滤函数：携带者不可被选为攻击目标（返回 False）。"""
    return lambda carrying, actor, skill: False
