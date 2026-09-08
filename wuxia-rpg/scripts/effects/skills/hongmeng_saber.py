"""鸿蒙刀势 - 鸿蒙刀法：刀势如鸿蒙初开、涤荡周身浊气，命中后移除自身所有非长效负面状态。

敌方全体攻击：引擎对每个命中敌方各调用一次 on_target_resolved（识破「全体」单次掷骰共享发动结果，
发动为真时各命中目标触发本钩子）。命中后清除携带者（自身）身上所有「非长效负面」状态
（战斗场景、剩余时间≥0、buff 类型为负向），长效负面（剩余时间<0）不受影响。

describe_skill_effect：非状态施加类（无 EFFECT_STATUS），描述用 EFFECT_MECHANIC 文案。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后涤荡自身，移除所有非长效负面状态"

from common import effect_loader as el

# 非长效负面判定口径与丹药净化/削减一致，集中于此供 on_target_resolved 复用
def _debuffs_of(char, buffs_data):
    return [e for e in char.get("状态效果", [])
            if e.get("场景", "战斗") == "战斗"
            and e.get("剩余时间", 0) >= 0
            and next((b for b in buffs_data.values() if b["id"] == e["id"]), {}).get("类型") == "负向"]


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    from common import status_manager as sm
    buffs_data = sm.load_buffs()
    removed = []
    for e in _debuffs_of(actor, buffs_data):
        name = sm.buff_name_of(e["id"])
        if sm.remove_status(actor, e):
            removed.append({"id": e["id"], "名称": name})
    return {"移除负面": removed} if removed else None
