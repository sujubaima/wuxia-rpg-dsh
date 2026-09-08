"""七星逆脉：按概率互换气血/内力结算去向。"""
import random

from combat import battle_engine as be

SKILL_NAME = "七星逆脉"
BASE_PROB = 0.40
MAX_PROB = 0.60


def trigger_prob(char):
    return MAX_PROB if be.get_skill_level(char, SKILL_NAME) >= 10 else BASE_PROB


def on_settle(source, ctx):
    """仅当事方为携带者且逆脉触发时改写结算池。"""
    char = source["持有者"]
    event = ctx["事件"]
    kind = event["事件"]
    if kind == "消耗":
        if event.get("行动者") is not char or event.get("预演"):
            return
        if random.random() >= trigger_prob(char):
            return
        x = event.get("扣内力", 0)
        event["扣内力"] = 0
        event["扣气血"] = event.get("扣气血", 0) + x
    elif kind == "伤害":
        if event.get("目标") is not char or random.random() >= trigger_prob(char):
            return
        x = min(char.get("内力", 0), event.get("落气血", 0))
        event["落内力"] = event.get("落内力", 0) + x
        event["落气血"] = 0
    elif kind == "治疗":
        if event.get("目标") is not char or random.random() >= trigger_prob(char):
            return
        room = max(0, be.status_attr(char, "内力上限") - char.get("内力", 0))
        x = min(event.get("落气血", 0), room)
        event["落气血"] -= x
        event["落内力"] = event.get("落内力", 0) + x
    elif kind == "内力恢复":
        if event.get("目标") is not char or random.random() >= trigger_prob(char):
            return
        room = max(0, be.status_attr(char, "气血上限") - char.get("气血", 0))
        x = min(event.get("落内力", 0), room)
        event["落内力"] -= x
        event["落气血"] = event.get("落气血", 0) + x
