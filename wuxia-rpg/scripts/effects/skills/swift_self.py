"""轻灵剑意 - 越女剑法：自身施加疾速"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_STATUS = "swift"
EFFECT_DURATION = 1
EFFECT_TARGET = "self"

from common import effect_loader as el


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    # 持续时长 = 基准 + 武学十境「特效持续时间」加成（无加成则仍为1）。
    # 自身施加时引擎会 +1 计时补偿，使其恰好撑到下一次自己回合行动后消除。
    dur = EFFECT_DURATION + el.effect_dur_bonus(skill)
    apply_status(actor, "swift", dur)
    return {"自身施加状态": "swift"}
