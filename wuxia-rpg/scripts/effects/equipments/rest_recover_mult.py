"""休息恢复倍率

params 形如 {"气血": mult, "内力": mult}，缺省资源倍率为 1。
例：木剑 {"内力": 2} → 休息时仅内力恢复量 ×2，气血不变。
"""

def modify_rest_recover(actor, recover, params):
    hp, mp = recover
    params = params or {}
    return hp * params.get("气血", 1), mp * params.get("内力", 1)
