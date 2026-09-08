"""人剑合一 - 不装备剑类武器亦可施展剑法武学

紫霞神功运转所生之长效状态。携带者施展剑法武学时豁免武器门禁——
即便未佩剑，亦可凭无形剑气御使剑招。机制经引擎 on_weapon_check 钩子豁免，
无需在引擎中硬编码特定状态 id。
"""


def on_weapon_check(char, skill, blocked):
    """剑法武学武器不符时豁免。blocked=True 表示当前按武器规则被禁。"""
    return blocked and skill.get("类型") == "剑法"
