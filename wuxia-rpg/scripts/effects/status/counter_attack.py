"""反击：携带者受敌方攻击命中时自身时序+100。"""

ATB_ADVANCE = 100


def on_target_confirmed(source, ctx):
    char = source["持有者"]
    event = ctx["事件"]
    if event.get("事件") != "攻击命中" or event.get("目标") is not char:
        return
    attacker = event.get("攻击方")
    if not attacker or attacker.get("阵营") == char.get("阵营"):
        return
    before = char.get("充能", 0)
    char["充能"] = before + ATB_ADVANCE
    return [{"目标": char["名称"], "变化": ATB_ADVANCE,
             "原值": before, "新值": char["充能"]}]
