"""高远无极：受敌方攻击命中时令攻击方时序回退，十境自身前推。"""
from combat import battle_engine as be

ATB_REGRESS = 50
ATB_ADVANCE = 50
SKILL_NAME = "高远无极功"


def on_target_confirmed(source, ctx):
    char = source["持有者"]
    event = ctx["事件"]
    if event.get("事件") != "攻击命中" or event.get("目标") is not char:
        return
    attacker = event.get("攻击方")
    if not attacker or attacker.get("阵营") == char.get("阵营"):
        return
    before = attacker.get("充能", 0)
    attacker["充能"] = before - ATB_REGRESS
    events = [{"目标": attacker["名称"], "变化": -ATB_REGRESS,
               "原值": before, "新值": attacker["充能"]}]
    if be.get_skill_level(char, SKILL_NAME) >= 10:
        self_before = char.get("充能", 0)
        char["充能"] = self_before + ATB_ADVANCE
        events.append({"目标": char["名称"], "变化": ATB_ADVANCE,
                       "原值": self_before, "新值": char["充能"]})
    return events
