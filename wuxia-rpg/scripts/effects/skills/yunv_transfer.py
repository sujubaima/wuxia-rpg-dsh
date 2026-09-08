"""素心移厄 - 玉女素心剑：命中后随机将自身一个负面状态转移给目标。"""

import copy
import random

from common import status_manager as sm

EFFECT_MECHANIC = "命中后随机将自身一个负面状态转移给目标"
_BASE_FIELDS = {"id", "剩余时间", "场景", "来源", "来源类型"}


def _debuffs_of(char, buffs_data):
    types = {b["id"]: b.get("类型") for b in buffs_data.values()}
    return [e for e in char.get("状态效果", [])
            if e.get("场景", "战斗") == "战斗"
            and types.get(e.get("id")) == "负向"]


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    debuffs = _debuffs_of(actor, sm.load_buffs())
    if not debuffs:
        return None

    entry = random.choice(debuffs)
    moved = copy.deepcopy(entry)
    if not sm.remove_status(actor, entry):
        return None

    extra = {key: value for key, value in moved.items() if key not in _BASE_FIELDS}
    sm.apply_status(
        target,
        moved["id"],
        moved.get("剩余时间", 0),
        source=moved.get("来源"),
        source_type=moved.get("来源类型"),
        scene=moved.get("场景", "战斗"),
        extra=extra,
    )
    return {
        "状态转移": [{
            "id": moved["id"],
            "名称": sm.buff_name_of(moved["id"]),
            "来源目标": actor["名称"],
            "转移目标": target["名称"],
            "持续时间": moved.get("剩余时间", 0),
        }]
    }
