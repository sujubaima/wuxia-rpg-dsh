"""心疾 - 无法借休息恢复内力，且内力上限-20%

心法「西子捧心诀」运转所致之心疾，自第一境起与【西子捧心】同施。
持有此状态者休息时不再恢复内力（气血本就不由休息恢复），
且内力上限削减20%——均经 on_modify_attr 钩子由引擎读接口
（status_attr）实时折算：内力上限×0.8、休息内力恢复比例归0，
状态移除即自动失效，无需手动改值/还原。
"""


def on_modify_attr(char, attr_name, base_value):
    if attr_name == "内力上限":
        return round(base_value * 0.8)
    if attr_name == "休息内力恢复":
        return 0.0
    return base_value
