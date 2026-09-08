"""九宫锁式 - 九宫八卦剑：命中后随机延长目标一门上场武学的冷却。"""

import random

from combat import battle_engine as be

EFFECT_MECHANIC = "命中后随机选择目标一门上场武学：未冷却则进入1回合冷却，否则剩余冷却+1回合"


def on_target_resolved(source, ctx):
    target = ctx["目标"]
    skills = be.load_skills()
    candidates = []
    for name in be.get_active_skill_names(target):
        data = skills.get(name)
        if data and data.get("类型") != "心法" and name not in candidates:
            candidates.append(name)
    if not candidates:
        return None

    chosen = random.choice(candidates)
    cooldowns = target.setdefault("冷却", {})
    before = max(0, cooldowns.get(chosen, 0))
    after = before + 1 if before else 2
    cooldowns[chosen] = after
    return {
        "冷却变化": [{
            "目标": target["名称"],
            "武学": chosen,
            "原值": before,
            "新值": after,
            "新增冷却": before == 0,
        }]
    }
