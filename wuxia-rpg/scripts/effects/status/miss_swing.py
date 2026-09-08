"""扑空：携带者攻击该状态施加者时精准按50%计算。"""

MULT = 0.5


def on_target_check(source, ctx):
    char = source["持有者"]
    event = ctx["事件"]
    if event.get("攻击方") is not char:
        return
    target = event.get("目标")
    src = next((e.get("施加者") for e in source["条目"] if e.get("施加者")), None)
    if src and target and target.get("名称") == src:
        event["攻击精准"] = round(event.get("攻击精准", 0) * MULT)
