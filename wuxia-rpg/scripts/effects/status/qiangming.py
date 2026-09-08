"""强命：气血将归零时保留1点气血，并消耗一层。"""
from common import status_manager as sm

STATUS_ID = "qiangming"


def on_before_commit(source, ctx):
    """最终写账前限制致命气血损失；同一次结算只消耗一层。"""
    char = source["持有者"]
    event = ctx["事件"]
    kind = event.get("事件")
    if kind == "伤害":
        if event.get("目标") is not char:
            return
        hp_key = "落气血"
    elif kind == "消耗":
        if event.get("行动者") is not char:
            return
        hp_key = "扣气血"
    else:
        return

    hp = char.get("气血", 0)
    hp_loss = event.get(hp_key, 0)
    if hp <= 0 or hp_loss <= 0 or hp_loss < hp:
        return

    event[hp_key] = max(0, hp - 1)
    event["强命保命"] = {"目标": char["名称"], "名称": sm.buff_name_of(STATUS_ID)}
    sm.remove_status(char, source["条目"][0])
