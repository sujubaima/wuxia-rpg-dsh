"""封剑锁技 - 长空神剑：对目标施加封技，剑势锁其武学路径。必发（识破类型=无）。

命中后给目标施加封技——默认禁 2-3 品武学；满境（lv10）封禁品级升至 1-3 品（连1品亦锁）。
持续时长含十境「特效持续时间」加成。封技不可叠加，重复施取 max 时长；满境注入的
封禁品级会覆盖目标身上既存封技条目（更强封禁留存）。

describe_skill_effect：经 effect_brief 钩子让状态简述随等级变（满境括号内品级随之扩展），
与 on_target_resolved 的满境注入同源（均判 _等级>=10），无需十境「特效增强」追加文案。
"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "fengji"
EFFECT_DURATION = 2
EFFECT_TARGET = "target"

from common import effect_loader as el


def _blocked_tiers(level):
    """当前等级封禁品级集：满境 1-3 品，否则默认 2-3 品。"""
    return [1, 2, 3] if (level or 1) >= 10 else [2, 3]


def effect_brief(skill, level):
    """覆盖状态简述的括号部分：随等级反映封禁品级（满境 1-3 品）。"""
    tiers = _blocked_tiers(level)
    return f"【封技】（无法使用{tiers[0]}-{tiers[-1]}品武学）"


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    # 封禁品级随施术等级：满境 1-3 品，否则 2-3 品（缺省）。经 extra 注入状态条目，
    # fengji skill_filter 据此判定；不可叠加重复施时 extra 仍覆盖旧值（更强封禁留存）。
    tiers = _blocked_tiers(skill.get("_等级", 1))
    apply_status(target, EFFECT_STATUS, dur, extra={"封禁品级": tiers})
    return {"施加状态": EFFECT_STATUS}
