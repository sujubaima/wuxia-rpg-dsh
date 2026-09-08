"""椎心八法 - 刺客奇兵：命中后令目标所有非长效负面状态持续时间翻倍。

非长效 = 有限时长（剩余时间≥0）。「翻倍」就地改写各条目剩余时间，不改可叠加层数。
长效状态（剩余<0）与战斗外场景状态不动。
"""
# 特效说明（说明生成读取）
EFFECT_MECHANIC = "命中后令目标所有非长效负面状态持续时间翻倍"

from common import dao as dq


def on_target_resolved(source, ctx):
    actor = ctx["行动者"]
    target = ctx["目标"]
    skill = ctx["行动"]
    result = ctx["结果"]
    characters = ctx["角色列表"]
    apply_status = ctx["apply_status"]
    buffs = dq.load_all("状态")
    affected = []
    for e in target.get("状态效果", []):
        if e.get("场景", "战斗") != "战斗" or e.get("剩余时间", 0) < 0:
            continue
        binfo = buffs.get(_buff_name_by_id(e["id"]))
        if not binfo or binfo.get("类型") != "负向":
            continue
        before = e["剩余时间"]
        e["剩余时间"] = before * 2
        affected.append({"目标": target["名称"], "id": e["id"],
                         "名称": binfo.get("名称", e["id"]),
                         "原剩余": before, "新剩余": e["剩余时间"]})
    return {"加剧负面": affected} if affected else None


def _buff_name_by_id(status_id):
    """状态 id → buff 数据键（中文「名称」）。load_all 以名称为键。"""
    for b in dq.load_all("状态").values():
        if b.get("id") == status_id:
            return b.get("名称")
    return None
