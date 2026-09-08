"""巫蛊 - 每回合结束时削减携带者气血上限（以受术时基值的一定比例线性累减），溢出气血抹平；
状态移除后气血上限恢复、气血值不恢复。

与破防/心疾同源：纯查询型 on_modify_attr 钩子，绝不改 char["气血上限"] 池子、
绝不碰 char["气血"] 当前值。上限值由 status_attr(char,"气血上限") 查询时现算，
当前值联动（夹紧/抹平）由引擎统一的 clamp_pool 处理。

削减比例由施术武学（秘法钉头箭）等级决定，满境(10境)10%、1-9境7%，随巫蛊条目
「削减比例」字段走（施加方经 extra 写入）。巫蛊「可延长」单实例，on_modify_attr
从携带者状态里查巫蛊条目读该字段算比例（缺省回退 10%）。

on_apply(char, entry)：受术时锁定基数 = 二级属性基值「气血上限」（含武学与装备加成，
不含瞬时状态钩子），存于角色实例私有键 _巫蛊基数；初始化回合计数 _巫蛊回合=0。
可延长状态——刷新时长不重触 on_apply，沿用首次基数与计数（削减比例经 extra 覆盖更新）。

on_turn_end(char, characters)：每回合递增 _巫蛊回合 计数器，返回「上限削减」事件
交引擎 apply_dot_events → clamp_pool 夹紧当前气血、上报溢出损血。纯计数推进，不碰池子。

on_modify_attr(char, attr_name, base_value)：查询「气血上限」时返回
base_value - round(基数×比例)×回合数（线性 N×比例×基数，非指数衰减；下限 1）。

on_removed(char)：仅清理基数/计数键。不还原上限——钩子移除后 status_attr 自动回到基值，
当前气血不动（clamp_pool 只下不上），满足「移除后上限恢复、气血不恢复」。

时序：每经过携带者自己一回合 → on_turn_end → 计数++ → 之后所有 status_attr("气血上限")
读取按新计数折算（读晚于写）。
"""
DEFAULT_RATIO = 0.10  # 削减比例缺省（条目未带「削减比例」时）
BASE_KEY = "_巫蛊基数"
TURN_KEY = "_巫蛊回合"


def _deduct_ratio(char):
    """巫蛊每回合削减基数比例：取携带者巫蛊条目记的施术比例，缺省 10%。"""
    eff = next((e for e in char.get("状态效果", []) if e.get("id") == "wugu"), None)
    if not eff:
        return DEFAULT_RATIO
    return eff.get("削减比例", DEFAULT_RATIO)


def on_apply(char, entry):
    """受术时锁定削减基数（二级属性基值，含武学与装备加成）并初始化回合计数。"""
    char[BASE_KEY] = char.get("二级属性", {}).get("气血上限", 0)
    char[TURN_KEY] = 0


def on_turn_end(char, characters):
    """回合结束：递增回合计数，请求引擎夹紧当前气血到削减后的有效上限。"""
    char[TURN_KEY] = char.get(TURN_KEY, 0) + 1
    return [{"类型": "上限削减", "池": "气血", "来源": "巫蛊", "目标": char["名称"]}]


def on_modify_attr(char, attr_name, base_value):
    """查询气血上限时按回合计数线性削减（基数×比例×已过回合数）。"""
    if attr_name != "气血上限":
        return base_value
    base = char.get(BASE_KEY, 0)
    if base <= 0:
        return base_value
    turns = char.get(TURN_KEY, 0)
    if turns <= 0:
        return base_value
    deduct = round(base * _deduct_ratio(char)) * turns
    return max(1, base_value - deduct)


def on_removed(char):
    """状态移除：清理基数/计数键。上限由钩子移除自动回基值，气血不动。"""
    char.pop(BASE_KEY, None)
    char.pop(TURN_KEY, None)
