"""夜来风雨势 - 命中后涤荡目标周身增益，移除其所有非长效正向状态。

敌方全体攻击：引擎对每个命中敌方各调用一次 on_target_resolved（识破「独立」逐目标掷骰）。
命中且识破成功后，清除目标身上所有「非长效正向」状态（战斗场景、剩余时间≥0、
buff 类型为正向），长效正向（剩余时间<0）不受影响。

describe_skill_effect：非状态施加类（无 EFFECT_STATUS），描述用 EFFECT_MECHANIC 文案。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后涤荡目标周身增益，移除所有非长效正向状态"

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    from common import status_manager as sm
    buffs_data = sm.load_buffs()
    # 非长效正向判定口径与鸿蒙涤荡一致（类型取正向、剩余时间≥0），仅作用对象改为目标
    removed = []
    for e in char_target_buffs(target, buffs_data):
        name = sm.buff_name_of(e["id"])
        if sm.remove_status(target, e):
            removed.append({"id": e["id"], "名称": name, "目标": target["名称"]})
    return {"移除增益": removed} if removed else None


def char_target_buffs(char, buffs_data):
    """目标身上所有「非长效正向」状态（战斗场景、剩余时间≥0、类型为正向）。"""
    return [e for e in char.get("状态效果", [])
            if e.get("场景", "战斗") == "战斗"
            and e.get("剩余时间", 0) >= 0
            and next((b for b in buffs_data.values() if b["id"] == e["id"]), {}).get("类型") == "正向"]
