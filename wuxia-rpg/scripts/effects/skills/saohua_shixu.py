"""扫花时序 - 扫花诀：命中后使目标时序+100；十境额外使自身时序+50

必发（技能数据 识破类型=无），不经识破判定。目标时序（充能）前推一百点，
出手轮次立即提前。对内即用——本武学目标范围为我方单体。
十境：施展者自身时序同步前推五十点。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后使目标时序+100（无需识破）；十境时自身时序+50"

SEQ_PUSH = 100      # 目标时序前推量
SELF_SEQ_PUSH = 50  # 十境时自身时序前推量


def on_target_resolved(source, ctx):
    """命中后目标充能 +100（十境另使自身 +50），回报时序变化事件。"""
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    events = []
    before = target.get("充能", 0)
    target["充能"] = before + SEQ_PUSH
    events.append({"目标": target["名称"], "变化": SEQ_PUSH,
                   "原值": before, "新值": target["充能"]})
    if skill.get("_等级", 1) >= 10:
        self_before = actor.get("充能", 0)
        actor["充能"] = self_before + SELF_SEQ_PUSH
        events.append({"目标": actor["名称"], "变化": SELF_SEQ_PUSH,
                       "原值": self_before, "新值": actor["充能"]})
    return {"时序变化": events}
