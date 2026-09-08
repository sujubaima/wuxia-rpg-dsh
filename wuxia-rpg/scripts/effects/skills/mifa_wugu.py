"""秘法钉头箭 - 命中后对目标施加巫蛊（7回合），令其气血上限逐回合削减。

命中后对目标施加【巫蛊】7回合——携带者每回合结束气血上限削减受术时基值的一定比例
（线性累减）：满境(10境)10%、1-9境7%。溢出气血抹平；状态移除后上限恢复、气血不恢复。
机制见 effects/status/wugu.py 的 on_modify_attr 计数器方案。
持续时长含十境「特效持续时间」加成。识破类型「无」：命中即触发，无需识破掷骰。

describe_skill_effect：状态施加类，描述由 EFFECT_STATUS 自动生成；
削减比例随施术等级经 effect_brief 显示、经 extra 写入巫蛊条目供钩子读。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "wugu"
EFFECT_DURATION = 7
EFFECT_TARGET = "target"
RATIO_BASE = 0.07   # 1-9境每回合削减基数比例
RATIO_MAX = 0.10    # 10境每回合削减基数比例

from common import effect_loader as el


def effect_brief(skill, level):
    """覆盖状态简述的括号部分：随等级反映削减比例（满境10%、余境7%）。"""
    pct = int(RATIO_MAX * 100) if (level or 1) >= 10 else int(RATIO_BASE * 100)
    return f"【巫蛊】（每回合结束时削减气血上限{pct}%（以受术时气血上限为基），溢出气血抹平；移除后上限恢复、气血不恢复）"


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    # 削减比例随施术等级：满境10%、1-9境7%。经 extra 注入巫蛊条目供钩子读。
    level = skill.get("_等级", 1)
    ratio = RATIO_MAX if level >= 10 else RATIO_BASE
    apply_status(target, EFFECT_STATUS, dur, extra={"削减比例": ratio})
    return {"施加状态": EFFECT_STATUS}
