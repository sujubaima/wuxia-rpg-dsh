"""烛龙迟滞 - 烛龙枪法：命中后使目标时序-100。
烛龙睁目，枪势沉滞，迟敌出招半拍。需识破判定（独立）。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后使目标时序-100"

SEQ_PUSH = -100  # 目标时序前推量（负为延后）


def on_target_resolved(source, ctx):
    """命中后目标充能 -100，回报时序变化事件。"""
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    before = target.get("充能", 0)
    target["充能"] = before + SEQ_PUSH
    return {"时序变化": [{"目标": target["名称"], "变化": SEQ_PUSH,
                          "原值": before, "新值": target["充能"]}]}
