"""霸体：将一次受到的技能伤害无效化，并消耗一层。"""
from common import status_manager as sm

STATUS_ID = "bati"


def on_settle(source, ctx):
    """携带者受技能伤害时无效化本次伤害并消耗一层霸体。"""
    char = source["持有者"]
    event = ctx["事件"]
    if event.get("事件") != "伤害":
        return
    if event.get("目标") is not char:
        return
    if event.get("攻击方") is None:
        return
    if event.get("落气血", 0) <= 0:
        return
    entry = source["条目"][0]
    event["落气血"] = 0
    event["落内力"] = event.get("落内力", 0)
    event["霸体抵挡"] = {"目标": char["名称"], "名称": sm.buff_name_of(STATUS_ID)}
    sm.remove_status(char, entry)
