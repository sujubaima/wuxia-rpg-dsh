"""腥红刀法 - 嗜血刀意：刀锋饮血，命中后汲取对方气血内力反哺自身。

命中后按本次对目标造成伤害的比例恢复使用者气血与内力（敌方全体时逐目标各结一次，
总和等价于总伤害×比例）。基础30%，满境（lv10）升至50%。识破类型「独立」——逐目标各掷一次，
未发动的目标其伤害不计入吸血（引擎门控：识破失败则不调 on_target_resolved）。恢复经 settle 事件落账
（如【七星逆脉】可改写去向），与休息/物品/DOT 同源。满境比例提升文案见十境表「特效增强」。

describe_skill_effect：非状态施加类（无 EFFECT_STATUS），描述用 EFFECT_MECHANIC 文案 +
十境「特效增强」附加（满境比例提升）。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后按造成伤害的30%恢复自身气血与内力"

from combat import battle_engine as be  # 落账走 settle 事件（与 gaoyuan_wuji/qixing_nimai 同口径）

RATIO = 0.30        # 基础吸血比例
RATIO_MAX = 0.50    # 满境（lv10）吸血比例


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 比例随等级：满境50%，否则30%（AOE 逐目标各结，总和等价总额×比例）
    ratio = RATIO_MAX if skill.get("_等级", 1) >= 10 else RATIO
    dmg = result.get("伤害", 0) or 0
    if dmg <= 0:
        return None
    gain = max(1, round(dmg * ratio))
    hp0 = actor["气血"]
    mp0 = actor["内力"]
    # 经 settle 事件落账（治疗 + 内力恢复），供【七星逆脉】等改写去向
    ctx["settle"]({"事件": "治疗", "攻击方": None, "目标": actor,
                           "落气血": gain, "落内力": 0, "来源": skill["名称"] + "·嗜血"})
    ctx["settle"]({"事件": "内力恢复", "攻击方": None, "目标": actor,
                           "落气血": 0, "落内力": gain, "来源": skill["名称"] + "·嗜血"})
    out = {"嗜血恢复": gain}
    if actor["气血"] != hp0:
        out["嗜血气血变化"] = {"原值": hp0, "新值": actor["气血"]}
    if actor["内力"] != mp0:
        out["嗜血内力变化"] = {"原值": mp0, "新值": actor["内力"]}
    return out

