"""缠磨同归 - 百缠手：命中后把自身与目标的时序（充能）设为二者均值。
丐帮缠斗拳意，出手黏滞拉扯，消磨对手亦拖缓己身，使双方出招节拍趋同。需识破判定（独立）。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后将自身与目标时序（充能）设为二者均值"


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    a = actor.get("充能", 0)
    t = target.get("充能", 0)
    mid = (a + t) / 2
    actor["充能"] = mid
    target["充能"] = mid
    # 时序变化事件：双方各按其增量呈现（变化由正负决定方向）
    return {"时序变化": [
        {"目标": actor["名称"], "变化": mid - a, "原值": a, "新值": mid},
        {"目标": target["名称"], "变化": mid - t, "原值": t, "新值": mid},
    ]}
