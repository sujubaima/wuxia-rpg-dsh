"""焚身 - 回合内使用技能造成的伤害，自身按比例承担

结算阶段钩子 on_settle(char, event)：引擎每次落账前广播结算事件。当携带者为本回合
行动者（伤害事件的 攻击方）时，累加其造成的伤害到本回合蓄值——单体技累加该目标
一击，敌方全体技逐目标累加（自然成全伤之和）。

回合结束钩子 on_turn_end(char, characters)：携带者本回合行动毕，将蓄值按反伤比例
折算后作为「持续伤害」上报（来源 焚身），由引擎 apply_dot_events 统一落账（经
【七星逆脉】等结算路由、记录、击败判定）。落账事件 攻击方=None，故本钩子不再二次
累加（无递归）。

回合开始钩子 on_turn_start：清空蓄值，每回合从零计起。

反伤比例由施术武学（鬼火书）等级决定，满境(10境)100%、1-9境60%，随焚身条目
「武学等级」字段走（施加方写入）。焚身「不可叠加」单条目，on_settle 从携带者
状态里查焚身条目读该字段算比例。

钩子只搬数值（蓄值/上报事件），不直接改写气血——落账由引擎单一改动源处理。
蓄值存于角色实例私有键 _焚身蓄，按角色区分，随角色字典回收自然清理。
"""
ACC_KEY = "_焚身蓄"
RATIO_BASE = 0.60   # 1-9境反伤比例
RATIO_MAX = 1.00   # 10境反伤比例


def _burn_ratio(char):
    """焚身反伤比例：取携带者焚身条目记的施术武学等级，满境1.0否则0.6。"""
    eff = next((e for e in char.get("状态效果", []) if e.get("id") == "fenshen"), None)
    if not eff:
        return RATIO_MAX
    return RATIO_MAX if eff.get("武学等级", 1) >= 10 else RATIO_BASE


def on_turn_start(char, characters):
    """回合开始：清空本回合蓄值。"""
    char[ACC_KEY] = 0
    return None


def on_settle(source, ctx):
    """结算阶段：携带者为伤害事件攻击方时，累加造成的伤害到蓄值。"""
    char = source["持有者"]
    event = ctx["事件"]
    if event.get("事件") != "伤害" or event.get("反伤"):
        return
    if event.get("攻击方") is not char:
        return  # 仅累加自身造成的伤害（敌方全体逐目标各触发一次，自然求和）
    char[ACC_KEY] = char.get(ACC_KEY, 0) + event.get("落气血", 0)


def on_turn_end(char, characters):
    """回合结束：将本回合造成的伤害总量按反伤比例反噬自身。"""
    total = char.get(ACC_KEY, 0)
    char[ACC_KEY] = 0  # 落账即清，避免重入或下回合残留
    if total <= 0:
        return None
    dmg = round(total * _burn_ratio(char))
    if dmg <= 0:
        return None
    return [{"类型": "持续伤害", "数值": dmg, "来源": "焚身", "目标": char["名称"]}]
