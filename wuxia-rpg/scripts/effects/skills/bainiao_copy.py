"""百鸟朝凤 - 百鸟朝凤枪：命中后复制目标身上所有增益状态至自身。
枪花灿烂如百鸟朝凤，敌之所长皆为我用。需识破判定（独立，命中后掷骰发动）。"""
# 特效说明（说明生成读取，与 on_target_resolved 同源）
EFFECT_MECHANIC = "命中后复制目标所有增益状态至自身"

from common import effect_loader as el
from common import status_manager as sm


def on_target_resolved(source, ctx):
    """命中后把目标身上所有正向（增益）状态复制到自身，保留各状态剩余时间。"""
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    buffs = sm.load_buffs()
    pos_ids = {b["id"] for b in buffs.values() if b.get("类型") == "正向"}
    # 目标身上的正向状态条目（战斗场景、有剩余时间）；按剩余时间排序便于稳定汇报
    copied = []
    for e in list(target.get("状态效果", [])):
        sid = e.get("id")
        if sid not in pos_ids:
            continue
        if e.get("场景", "战斗") != "战斗":
            continue
        dur = e.get("剩余时间", 0)
        if dur < 0:
            continue  # 长效（永久）状态不复制，避免无限继承
        # 收集原条目上的定制字段（extra，如焚身武学等级、巫蛊削减比例）一并复制
        extra = {k: v for k, v in e.items()
                 if k not in ("id", "剩余时间", "场景", "来源", "来源类型", "施加者")}
        # 重新施加到自身（走 on_apply 正常流程，如缥缈注册 filter）。
        # 自身施加时引擎会 +1 计时补偿，使其撑到下一次自己回合行动后消除。
        # on_target_resolved 的 apply_status 闭包签名为 (t, sid, dur, extra=None)，来源由闭包
        # 固定为本次武学，故经 extra 携带原条目定制字段。
        apply_status(actor, sid, dur, extra or None)
        copied.append({"id": sid, "名称": sm.buff_name_of(sid)})
    return {"复制增益": copied} if copied else None
