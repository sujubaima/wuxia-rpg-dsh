"""技能评分器：为 AI 决策提供技能的综合估值。

核心接口 `score_skill(base, resolved, actor, characters) → float`，综合威力、特效、
识破门槛、内力消耗等给出一个评分，供 ai_styles 加权选技。不同特效按其战术价值给不同
加分（控制类>必中类>自身增益>持续伤害/吸血），使带特效的技能在 AI 手中得到合理估值、
不再被纯威力埋没。

扩展点：后续若需某技能特例评分，可在 SKILL_OVERRIDES 注册「技能名→自定义评分函数」，
或新增特效类型到 EFFECT_SCORES。风格层（ai_styles）在评分基础上按倾向调整（勇猛偏威力、
谨慎偏低耗），不影响本评分器的通用估值。
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from common import dao as dq
from common import status_manager as sm

# 特效类型 → 战术价值分（叠加在威力基础分之上）。
# 控制/减益类（断筋、目盲、迷幻）最高——直接削弱对手输出与生存；
# 必中类次之——稳定命中、对高闪避目标尤 valuable；
# 自身增益（铁壁、疾速、回春、凝神）中——提升自身续航/节奏；
# 持续伤害（外伤）与吸血中低——伤害总量提升但非立竿见影。
EFFECT_SCORES = {
    "broken_tendon_strike": 0.8,   # 断筋：减速，削弱对方行动频率
    "zhanxie_finisher": 0.5,       # 击败目标后推进自身时序
    "sangong_strike": 0.9,          # 散功：废对方心法（攻防/增伤/反制等长效状态全失效）
    "changkong_fengji": 0.9,       # 封技：禁2-3品武学（废对方主力输出手段）
    "taiji_xuhao": 0.8,             # 虚耗：废对方内力续航（技能内力消耗+50%）
    "glamour_dazzle": 0.8,         # 目盲：精准大降，削弱对方命中
    "bicheng_mihuan": 0.7,         # 迷幻：控制类
    "bone_shatter": 0.5,           # 碎骨/外伤：持续流血，可叠加
    "ignore_dodge": 0.6,          # 必中：无视闪避，稳定命中
    "iron_guard": 0.6,            # 铁壁：自身防御增益
    "swift_self": 0.5,            # 疾速：自身速度增益
    "ningshen_self": 0.5,         # 凝神：自身增益
    "huichun_self": 0.5,          # 回春：自身持续回血
    "willow_drain": 0.4,          # 化气为柳：吸血/吸内
    "insightful_rally": 0.6,      # 识破类增益
    "xihe_reset_cooldown": 0.5,   # 冷却重置
    "xinyou_saber": 0.6,          # 辛酉刀特效
}

# 技能名 → 自定义评分函数 (base, resolved, actor, characters) → float。
# 用于个别需要特殊估值的技能（如机制特殊、与情境强相关者）。空则全走默认评分。
SKILL_OVERRIDES = {}


def _insight_rate(actor, characters):
    """估算该行动者对敌方平均识破的特效发动率（0~1）。

    识破判定：75 + (攻识破 − 对抗值) × 0.8，对抗值取敌方存活者识破均值。
    需识破判定的特效据此打折——识破高的角色能发挥特效技能，识破低则估值降低。
    仅用角色二级属性估算（不经状态修正），AI 决策无需精确到战斗实时。
    """
    my_insight = actor.get("二级属性", {}).get("识破", 0)
    foes = [c for c in characters
            if c["阵营"] != actor["阵营"] and c.get("气血", 0) > 0 and not c.get("逃走")]
    if not foes:
        return 1.0
    foe_insight = sum(c.get("二级属性", {}).get("识破", 0) for c in foes) / len(foes)
    rate = (75 + (my_insight - foe_insight) * 0.8) / 100.0
    return max(0.0, min(1.0, rate))


def score_skill(base, resolved, actor, characters):
    """综合评分一个技能供 AI 加权选技。返回正数分值。

    评分 = 威力基础分 + 特效分 × 识破发动率（需识破判定的特效打折）。
    威力取 resolved 的有效威力倍率；特效分按 EFFECT_SCORES 取值；
    自身增益类特效不受识破门槛影响（作用于自身无需识破对抗）。
    SKILL_OVERRIDES 命中则完全走自定义评分。
    """
    name = base.get("名称")
    if name in SKILL_OVERRIDES:
        return SKILL_OVERRIDES[name](base, resolved, actor, characters)

    power = resolved.get("威力倍率", 1.0) or 1.0
    score = power  # 威力基础分

    effect = base.get("技能特效")
    if effect:
        eff_score = EFFECT_SCORES.get(effect, 0.3)  # 未知特效给保守基础分
        # 需识破判定的特效（识破类型=独立/全体/自对抗）按发动率打折；
        # 识破类型=无 或 自身增益类特效不受识破门槛影响
        insight_type = base.get("识破类型")
        needs_insight = insight_type in ("独立", "全体", "自对抗")
        # 自身增益类（_self 后缀）作用于自身，不依赖对敌方识破
        is_self_buff = effect.endswith("_self") or effect in ("iron_guard",)
        if needs_insight and not is_self_buff:
            eff_score *= _insight_rate(actor, characters)
        score += eff_score

    return max(0.01, score)


def _debuff_count(char):
    """角色身上的非长效负面状态数（供净化/削减类物品估值）。"""
    return sum(1 for e in char.get("状态效果", [])
               if e.get("剩余时间", 0) >= 0
               and _buff_type(e.get("id")) == "负向")


def _buff_type(status_id):
    """读 buff 类型（正向/负向/中性）。找不到返回 None。"""
    for b in dq.load_all("状态").values():
        if b.get("id") == status_id:
            return b.get("类型")
    return None


def _foe_threat(characters, my_side):
    """敌方威胁度 0~1：敌方在场者总 HP% 越高威胁越大（供控敌道具估值）。"""
    foes = [c for c in characters
            if c["阵营"] != my_side and c.get("气血", 0) > 0 and not c.get("逃走")]
    if not foes:
        return 0.0
    total_hp = sum(c["气血"] for c in foes)
    total_cap = sum(sm.status_attr(c, "气血上限") for c in foes)
    return total_hp / total_cap if total_cap > 0 else 0.0


def score_item(item, actor, characters):
    """评分一个战斗消耗品供 AI 加权选用。返回非负分值（情境感知，非固定概率）。

    评分随情境动态变化——这正是「走评分而非固定概率」的体现：
    - 回气血丹药：分 ∝ 自身缺血比例（满血≈0、残血高），残血时才值得用；
    - 回春散（持续回血）：残血时中分；
    - 净化/削减/延长（清负面状态）：身上有非长效负面状态时才高分，无则≈0；
    - 控敌道具（时序/目盲）：按敌方威胁度估值，敌方强才值得用。
    满血且无负面状态时，丹药/净化类评分趋近 0，AI 自然不会浪费回合用它们。
    """
    eff = item.get("使用效果", {})
    if not eff:
        return 0.0
    my_side = actor["阵营"]
    hp_cap = max(1, sm.status_attr(actor, "气血上限"))
    hp_ratio = actor.get("气血", 0) / hp_cap
    missing = max(0.0, 1.0 - hp_ratio)  # 缺血比例 0~1

    # 回气血丹药：按回复量占气血上限比例 × 缺血程度（满血时趋近 0，不该浪费回合）
    heal = eff.get("回复气血")
    if heal:
        heal_ratio = min(1.0, heal / hp_cap)
        return heal_ratio * missing * 1.5  # 残血时接近 heal_ratio×1.5，满血时为 0

    # 回内力丹药（补气丸）：按回复量占内力上限比例 × 内力枯竭程度（满内力时为 0）
    mp_heal = eff.get("回复内力")
    if mp_heal:
        mp_cap = max(1, sm.status_attr(actor, "内力上限"))
        mp_ratio = actor.get("内力", 0) / mp_cap
        mp_missing = max(0.0, 1.0 - mp_ratio)
        heal_ratio = min(1.0, mp_heal / mp_cap)
        return heal_ratio * mp_missing * 1.5

    # 施加状态（回春散对自己、石灰粉对敌方目盲）
    st = eff.get("施加状态")
    if st:
        sid = st.get("id", "")
        btype = _buff_type(sid)
        if btype == "正向":  # 回春等自身增益：残血时中分
            return 0.6 * missing
        if btype == "负向":  # 石灰粉目盲等控敌：按敌方威胁度
            return 0.8 * _foe_threat(characters, my_side)
        return 0.3

    # 净化（清非长效负面状态）：身上有负面状态才高分
    if "净化" in eff:
        return 0.7 * min(1.0, _debuff_count(actor) / 2.0)

    # 削减（所有非长效负面状态 -N 回合）：同净化，看负面状态数
    if "削减" in eff:
        return 0.5 * min(1.0, _debuff_count(actor) / 2.0)

    # 延长（所有非长效正面状态 +N 回合）：有正面限时状态才用
    if "延长" in eff:
        pos = sum(1 for e in actor.get("状态效果", [])
                  if e.get("剩余时间", 0) >= 0 and _buff_type(e.get("id")) == "正向")
        return 0.4 * min(1.0, pos / 2.0)

    # 时序道具（如爆竹令目标充能-100，延后出招）：按敌方威胁度
    if "时序" in eff:
        return 0.5 * _foe_threat(characters, my_side)

    return 0.0


def score_target(actor, target, characters):
    """目标价值（作为技能评分的乘数，0.5~1.5）：综合补刀价值与威胁压制。

    - 补刀价值：目标越残血，越值得收尾，乘数越高（满血 1.0、濒死趋近 1.5）；
    - 威胁压制：目标攻击力相对敌方均值越高，越值得优先削弱（高威胁 ×1.2、低威胁 ×0.9）。
    使「选技能」与「选目标」联动——同一技能打残血高威胁目标得分最高，
    打满血低威胁目标得分最低，AI 自然倾向补刀与压制威胁，而非随机选目标。
    """
    hp_ratio = target.get("气血", 0) / max(1, sm.status_attr(target, "气血上限"))
    # 补刀价值：满血1.0、残血趋近1.5
    finish = 1.0 + 0.5 * (1.0 - hp_ratio)
    # 威胁压制：目标攻击力相对敌方在场者均值
    my_side = actor["阵营"]
    foes = [c for c in characters
            if c["阵营"] != my_side and c.get("气血", 0) > 0 and not c.get("逃走")]
    if foes:
        atks = [c.get("二级属性", {}).get("攻击力", 0) for c in foes]
        avg = sum(atks) / len(atks) if atks else 0
        t_atk = target.get("二级属性", {}).get("攻击力", 0)
        threat = 1.0 + 0.2 * ((t_atk - avg) / max(1, avg)) if avg > 0 else 1.0
        threat = max(0.9, min(1.2, threat))
    else:
        threat = 1.0
    return finish * threat


def _has_xinji(actor):
    """角色是否带心疾（西子捧心诀所致，休息不回气血内力）。"""
    return any(e.get("id") == "xinji" for e in actor.get("状态效果", []))


def score_rest(actor):
    """休息价值（作为候选行动的评分，与技能/物品同尺度竞争）。

    残血（缺血）+ 内力枯竭时休息价值高；满血满内力时趋近 0（不如出招）。
    心疾修者休息回不了气血内力，价值大打折扣（避免无意义空过）——但仍保留
    极小保底，使内力耗尽、无可用技能时仍可休息（总比卡死强）。

    缺口权重视人物休息的实际恢复量：以默认内力恢复率 10% 为基准校准（权重 = 恢复率 × 8，
    默认内力权重 0.8 沿用旧感；休息回血属性非零者其气血项随之计入）。恢复越快，为补它而
    空过一回合越值；毫无恢复属性则对应项趋 0，自然倾向出招。
    """
    REST_SCALE = 8  # 默认 10% 内力恢复 → 权重 0.8 的校准系数
    hp_cap = max(1, sm.status_attr(actor, "气血上限"))
    mp_cap = max(1, sm.status_attr(actor, "内力上限"))
    sub = actor.get("二级属性", {})
    hp_gain = sub.get("休息气血恢复", 0)
    mp_gain = sub.get("休息内力恢复", 0.10)
    hp_missing = max(0.0, 1.0 - actor.get("气血", 0) / hp_cap)
    mp_missing = max(0.0, 1.0 - actor.get("内力", 0) / mp_cap)
    # 基础休息价值：缺口 × 校准后的恢复权重（满状态时≈0）
    base = (hp_missing * hp_gain + mp_missing * mp_gain) * REST_SCALE
    if _has_xinji(actor):
        # 心疾：休息不回气血内力，价值仅剩保底（避免无意义空过，但远低于出招/物品）
        return base * 0.05
    return base


def _team_hp_pct(characters, side):
    """队伍总 HP%：在场者气血之和 / 全队（含倒下/逃走者）气血上限之和。"""
    members = [c for c in characters if c["阵营"] == side]
    total_cap = sum(sm.status_attr(c, "气血上限") for c in members)
    if total_cap <= 0:
        return 0.0
    total_hp = sum(c["气血"] for c in members
                   if c.get("气血", 0) > 0 and not c.get("逃走"))
    return total_hp / total_cap


def _disadvantage(actor, characters):
    """己方劣势度 0~1：对方队伍总HP% − 己方队伍总HP%，钳制到 [0,1]。

    0 = 占优或均势（无脱身之意），1 = 己方濒灭、对方满血。逃跑/认输评分据此增长。
    """
    my_side = actor["阵营"]
    my_pct = _team_hp_pct(characters, my_side)
    foe_pct = max((_team_hp_pct(characters, c["阵营"])
                   for c in characters if c["阵营"] != my_side), default=0.0)
    return max(0.0, min(1.0, foe_pct - my_pct))


def score_flee(actor, characters):
    """逃跑评分（作为候选行动，与技能/物品/休息同尺度竞争）。

    随劣势度二次方增长。双重门槛（用户决策 2026-08）：
    - 劣势度 > 0.6 才入候选（血差显著才考虑脱身）
    - 自身气血 < 20% 上限（濒死方肯走）
    是否允许逃跑由调用方控制（allow_escape=False 时不入候选）。
    """
    dis = _disadvantage(actor, characters)
    if dis <= 0.6:
        return 0
    hp_pct = actor.get("气血", 0) / max(1, sm.status_attr(actor, "气血上限"))
    if hp_pct >= 0.2:
        return 0
    return 1.5 * 0.7 * dis * dis  # 逃跑评分已下调30%


def score_surrender(actor, characters):
    """认输评分（作为候选行动）。

    随劣势度二次方增长。三重门槛（用户决策 2026-08）：
    - 己方只剩自己一人存活（不全队俱殁不降）
    - 劣势度 > 0.5 才入候选（血差显著才考虑认降）
    - 自身气血 < 25% 上限（重伤方肯降）
    是否允许认输由调用方控制（can_surrender=False 时不入候选，如我方AI队友）。
    """
    my_side = actor["阵营"]
    alive = sum(1 for c in characters
                if c["阵营"] == my_side and c.get("气血", 0) > 0 and not c.get("逃走"))
    if alive > 1:
        return 0
    dis = _disadvantage(actor, characters)
    if dis <= 0.5:
        return 0
    hp_pct = actor.get("气血", 0) / max(1, sm.status_attr(actor, "气血上限"))
    if hp_pct >= 0.25:
        return 0
    return 1.0 * 0.4 * dis * dis  # 认输评分已下调60%
