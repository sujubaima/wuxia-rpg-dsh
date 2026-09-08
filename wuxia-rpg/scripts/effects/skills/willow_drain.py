"""化气为柳 - 细柳剑法：命中后将50%伤害转化为内力伤害

该特效为细柳剑法的招意核心，无需识破判定，命中即触发：
将本次伤害的一半改伤内力，气血内力各损其半。
"""
# 特效说明（说明生成读取）
EFFECT_MECHANIC = "命中后将50%伤害转为内力伤害（必发，无需识破）"

from combat import battle_engine as be

MP_RATIO = 0.50  # 转为内力伤害的比例

def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dmg = result.get("伤害", 0)
    if dmg <= 1:
        return {}
    # 50% 转为内力伤害，余下 50% 仍伤气血
    mp_dmg = int(dmg * MP_RATIO)
    hp_dmg = dmg - mp_dmg

    # 退还多扣的气血（转为内力的那部分），改扣内力
    hp_before = result.get("目标气血变化", {}).get("原值", target["气血"] + mp_dmg)
    target["气血"] = min(be.status_attr(target, "气血上限"), target["气血"] + mp_dmg)
    mp_before = target.get("内力", 0)
    target["内力"] = max(0, mp_before - mp_dmg)

    # 更新结算字段，供战报渲染
    result["伤害"] = hp_dmg
    result["内力伤害"] = mp_dmg
    result["目标剩余气血"] = target["气血"]
    result["目标气血变化"] = {"原值": hp_before, "新值": target["气血"]}
    result["目标剩余内力"] = target["内力"]
    result["目标内力变化"] = {"原值": mp_before, "新值": target["内力"]}
    return {"气血伤害": hp_dmg, "内力伤害": mp_dmg}
