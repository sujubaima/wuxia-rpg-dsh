"""AI 战斗风格策略集。

每风格一个函数，签名一致：
    style_fn(actor, characters, skills_db, characters_db, available, allow_escape, can_surrender) -> action dict
- actor: 当前行动者（battle char dict）
- characters: 全部角色列表
- skills_db / characters_db: 武学库 / 角色库
- available: 已过滤的可用技能列表 [(base_skill, resolved_skill), ...]
- allow_escape: 本场是否允许逃跑（GM 战前判定）；我方AI队友会被引擎强制 False
- can_surrender: 是否允许认输；我方AI队友会被引擎强制 False（避免擅自认降致玩家被迫结束战斗）
返回 {"类型": "休息"} / {"类型": "武学",...} / {"类型": "逃跑"} / {"类型": "认输"}。

风格由角色 JSON 的「战斗风格」字段指定（缺省 = 平衡）。ai_decide 据字段分发到此模块。
技能/目标的加权抽样逻辑在此；可用技能过滤（冷却/心法/内力/武器）由 battle_engine 统一完成。
逃跑/认输：逃跑须 allow_escape，成败由引擎掷骰；认输须 can_surrender，则己方判负、对方胜。
不同风格据双方队伍总 HP% 差距与性格选择是否脱身/认降——勇猛者死战不退，谨慎者见势早走。
"""

import os
import sys
import random

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from combat import skill_scorer
from common import status_manager as sm

# 风格注册表：风格名 → 策略函数。ai_decide 据角色「战斗风格」字段取用，缺省平衡。
STYLES = {}


def style(name):
    """装饰器：注册一个战斗风格。"""
    def wrap(fn):
        STYLES[name] = fn
        return fn
    return wrap


# ---- 共用小工具 ----

def _enemies_of(actor, characters):
    # 在场敌方：气血>0 且 非逃走（逃走者同败阵，不被选为目标）；缥缈者无法被选为攻击目标，排除
    return [c for c in characters
            if c["阵营"] != actor["阵营"] and c.get("气血", 0) > 0
            and not c.get("逃走") and sm.is_targetable(c, actor, None)]


def _allies_of(actor, characters):
    # 在场我方（含自己）：给友方单体技能挑目标用
    return [c for c in characters
            if c["阵营"] == actor["阵营"] and c.get("气血", 0) > 0 and not c.get("逃走")]


def _pick_weighted(pool, weights, jitter=0.3):
    """按权重加权抽样一个元素。权重非负，全0则等概率。

    jitter 为随机扰动幅度：每个权重先乘 [1-jitter, 1+jitter] 随机因子，再叠加一个
    与权重最大值成比例的随机基底（基底 = jitter × max(weights) × random()）。乘法扰动
    平缓权重分布、加法基底给弱项保底——既保留风格倾向（强项仍占优），又使弱选项有
    合理出现率、避免每回合都选出同一「最优解」。jitter=0 退化为纯权重抽样。
    """
    if not pool:
        return None
    if sum(weights) <= 0:
        return random.choice(pool)
    if jitter > 0:
        base = jitter * max(weights)
        weights = [w * random.uniform(1 - jitter, 1 + jitter) + base * random.random()
                   for w in weights]
    return random.choices(pool, weights=weights, k=1)[0]


def _item_target(item_data, actor, characters):
    """物品目标：丹药对自己；道具对敌方存活者中目标价值最高者（残血高威胁优先）。"""
    sub = item_data.get("子类型")
    if sub == "道具":
        foes = _enemies_of(actor, characters)
        if not foes:
            return None
        best = max(foes, key=lambda c: skill_scorer.score_target(actor, c, characters))
        return best["名称"]
    return actor["名称"]  # 丹药默认自己


def _pick_action(available, battle_items, actor, characters,
                 bias_fn=None, item_weight=1.0, rest_weight=1.0,
                 allow_escape=False, can_surrender=True,
                 flee_weight=1.0, surrender_weight=1.0):
    """在可用武学(×目标) + 可用物品 + 休息 + 逃跑/认输中按综合评分加权抽一个，返回 action dict 或 None。

    - 武学：技能评分 × 目标价值。单体技对每个敌方目标各成一个候选（残血高威胁目标得分高），
      全体技一个候选（目标=敌方全体）。bias_fn 按风格调整技能评分。
    - 物品：score_item × item_weight，目标按 _item_target（道具选目标价值最高者）。
    - 休息：score_rest × rest_weight（残血/内力枯竭分高；心疾修者回不了气则极低）。
    - 逃跑/认输：score_flee/score_surrender × 风格权重，随劣势度二次方增长——劣势小则趋近0
      （不如出招），劣势大则高于出招（值得脱身/认降）。逃跑须 allow_escape，认输须 can_surrender
      （我方AI队友二者皆禁）。逃跑优先于认输体现在 flee 评分系数 > surrender。
    统一加权抽样 + 随机扰动。无候选返回 None。
    """
    candidates = []  # [(action_dict, score)]
    foes = _enemies_of(actor, characters)
    allies = [c for c in _allies_of(actor, characters) if c is not actor]
    for base, resolved in available:
        s = skill_scorer.score_skill(base, resolved, actor, characters)
        if bias_fn:
            s = bias_fn(base, resolved, s)
        if s <= 0:
            continue
        scope = base.get("目标范围")
        if scope == "敌方全体":
            candidates.append(({"类型": "武学", "技能": base, "目标": "敌方全体"}, s))
        elif scope and scope.startswith("我方单体"):
            # 与敌方单体同构：每个存活友军（不含自己）各成一个候选，不加目标权重
            # 「我方单体除自身」语义天然成立——allies 本就不含 actor
            for ally in allies:
                candidates.append(({"类型": "武学", "技能": base, "目标": ally["名称"]}, s))
        else:
            for foe in foes:
                tv = skill_scorer.score_target(actor, foe, characters)
                candidates.append(({"类型": "武学", "技能": base, "目标": foe["名称"]}, s * tv))
    for it in battle_items:
        data = it["数据"]
        # 状态物品过滤（如【封穴】禁用一切物品）：被禁物品不入候选
        if not all(fn(actor, data) for fn in sm.get_item_filters(actor)):
            continue
        target = _item_target(data, actor, characters)
        if target is None:
            continue
        s = skill_scorer.score_item(data, actor, characters) * item_weight
        if s <= 0:
            continue  # 情境不合适（如满血用回血丹药）不入候选
        candidates.append(({"类型": "物品", "物品": data, "目标": target}, s))
    # 休息候选：满状态时趋近 0，残血/内力枯竭时高
    rest_s = skill_scorer.score_rest(actor) * rest_weight
    if rest_s > 0:
        candidates.append(({"类型": "休息"}, rest_s))
    # 逃跑/认输候选：随劣势度增长，劣势大时值得脱身/认降
    if allow_escape:
        flee_s = skill_scorer.score_flee(actor, characters) * flee_weight
        if flee_s > 0:
            candidates.append(({"类型": "逃跑"}, flee_s))
    if can_surrender:
        sur_s = skill_scorer.score_surrender(actor, characters) * surrender_weight
        if sur_s > 0:
            candidates.append(({"类型": "认输"}, sur_s))
    if not candidates:
        return None
    weights = [c[1] for c in candidates]
    idx = _pick_weighted(list(range(len(candidates))), weights)
    return candidates[idx][0] if idx is not None else None


# ---- 风格实现 ----

def _bias_yongmeng(base, resolved, score):
    """勇猛倾向：偏重威力——评分按威力倍率放大，高威力技更占优（仍含特效分）。"""
    power = resolved.get("威力倍率", 1.0) or 1.0
    return score * (power ** 2)


def _bias_jinshen(base, resolved, score):
    """谨慎倾向：偏低耗——高内力消耗的技能扣分，偏好可持久战的低耗技（仍含特效分）。"""
    cost = resolved.get("内力消耗", 0) or 0
    return score / (1 + cost / 100.0)


@style("平衡")
def 平衡(actor, characters, skills_db, characters_db, available, allow_escape=False,
        can_surrender=True, battle_items=None):
    """平衡：综合评分(威力+特效×目标价值)选技/选物，休息/逃跑/认输评分参与竞争；
    劣势大时倾向脱身、脱不得则认降。"""
    action = _pick_action(available, battle_items or [], actor, characters,
                         allow_escape=allow_escape, can_surrender=can_surrender)
    return action or {"类型": "休息"}


@style("勇猛")
def 勇猛(actor, characters, skills_db, characters_db, available, allow_escape=False,
        can_surrender=True, battle_items=None):
    """勇猛：偏重威力的综合评分选技/选物，几乎不休、优先打高威胁目标；
    死战不退——绝不逃跑、绝不认输（flee/surrender_weight=0）；较少依赖物品。"""
    action = _pick_action(available, battle_items or [], actor, characters,
                         bias_fn=_bias_yongmeng, item_weight=0.5, rest_weight=0.1,
                         flee_weight=0.0, surrender_weight=0.0)
    return action or {"类型": "休息"}


@style("谨慎")
def 谨慎(actor, characters, skills_db, characters_db, available, allow_escape=False,
        can_surrender=True, battle_items=None):
    """谨慎：偏低耗的综合评分选技/选物、更倾向休息回气保命、优先补刀残血；
    见势早走——劣势时更易脱身/认降（flee/surrender_weight 高）；更善用物品保命。"""
    action = _pick_action(available, battle_items or [], actor, characters,
                          bias_fn=_bias_jinshen, item_weight=1.3, rest_weight=1.5,
                          allow_escape=allow_escape, can_surrender=can_surrender,
                          flee_weight=1.5, surrender_weight=1.3)
    return action or {"类型": "休息"}
