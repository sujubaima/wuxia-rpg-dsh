"""清都涤厄 - 清都十三剑：命中后随机移除自身一个非长效负面状态，剑势出尘、涤荡浊厄。

识破类型「独立」：命中后逐目标经引擎识破掷骰，通过则触发。
从自身「非长效负面」状态（战斗场景、剩余时间≥0、buff 类型为负向）中随机移除一个；
若无符合条件的负面状态则无动作。长效负面（剩余时间<0）不受影响。
"""
import random

EFFECT_MECHANIC = "命中后随机移除自身一个非长效负面状态"


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
    debuffs = _debuffs_of(actor, buffs_data)
    if not debuffs:
        return None
    e = random.choice(debuffs)
    name = sm.buff_name_of(e["id"])
    if sm.remove_status(actor, e):
        return {"移除负面": [{"id": e["id"], "名称": name}]}
    return None
