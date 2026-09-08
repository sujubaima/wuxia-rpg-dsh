"""辛酉刀法 - 戚家军绝学：刀势沉猛，命中后自身刀气激荡、攻守兼备，自施铁壁与强攻。

命中后自身施加2层2回合【铁壁】（每层防御力+20%）与2层2回合【强攻】（每层攻击力+20%），
攻守同涨。识破类型「独立」——逐目标掷骰发动。
层数/持续时长含十境加成。自身施加时引擎会 +1 计时补偿，使其恰好撑到下一次自己回合行动后消除。

describe_skill_effect：双状态自施（无单一 EFFECT_STATUS），走 EFFECT_MECHANIC 文案路径。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后自身铁壁、强攻各2层2回合"

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 自施铁壁2层 + 强攻2层，各持续2回合（时长含十境「特效持续时间」加成）
    dur = 2 + el.effect_dur_bonus(skill)
    stacks = 2 + el.effect_stack_bonus(skill)
    applied = []
    for _ in range(stacks):
        apply_status(actor, "iron_wall", dur)
    applied.append({"目标": actor["名称"], "id": "iron_wall", "名称": "铁壁",
                    "持续时间": dur, "层数": stacks})
    for _ in range(stacks):
        apply_status(actor, "qianggong", dur)
    applied.append({"目标": actor["名称"], "id": "qianggong", "名称": "强攻",
                    "持续时间": dur, "层数": stacks})
    return {"自身施加状态": applied}
