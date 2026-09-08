"""西子捧心 - 自身每存有一个负向状态(debuff)，攻击伤害+20%

心法「西子捧心诀」运转所生之境。按持有者当前负向状态个数计，每有一个伤害×1.20。
负向状态以 data/buffs/ 中 类型=="负向" 为准（如断筋、目盲、心疾）；西子捧心自身默认正向，
不计入；心疾为负向，自第一境随同施加，故运转者常驻至少一个负向状态（基线+20%）。

十境圆满（精进等级≥10）：西子捧心转为负向——自身亦计入增伤。
休息无法恢复气血之效由独立的【心疾】状态承担（运转即施加，见 effects/xinji.py）。
伤害计算阶段钩子：全场广播到，仅攻击方为自身时增伤（无关即 return）。
"""
from combat import battle_engine as be

DEBUFF_BONUS = 0.20
SELF_ID = "xizi_pengxin"
SKILL_NAME = "西子捧心诀"
DISPLAY_NAME = "西子捧心"


def on_damage_calc(source, ctx):
    """伤害计算阶段：攻击方为自身时按负向状态数乘增伤倍率并记入来源。"""
    char = source["持有者"]
    event = ctx["事件"]
    if event.get("攻击方") is not char:
        return
    id_to_type = {b["id"]: b.get("类型") for b in be.load_buffs().values()}
    # 十境圆满：西子捧心自身转为负向，计入增伤
    if be.get_skill_level(char, SKILL_NAME) >= 10:
        id_to_type[SELF_ID] = "负向"
    debuff_count = sum(1 for e in char.get("状态效果", [])
                       if id_to_type.get(e["id"]) == "负向")
    if debuff_count <= 0:
        return
    mult = round(1.0 + DEBUFF_BONUS * debuff_count, 4)
    event["增伤倍率"] = round(event.get("增伤倍率", 1.0) * mult, 4)
    event["增伤来源"].append({"状态": DISPLAY_NAME, "倍率": mult})
