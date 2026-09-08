"""封技 - 携带者无法使用封禁品级内的武学

无自身行为钩子。通过 skill_filter(eff) 工厂声明技能过滤函数：携带者品级落在状态条目
「封禁品级」集合内的武学不可用。默认封 2-3 品；施加方可向状态条目写入「封禁品级」
定制（如长空神剑满境封 1-3 品）。filter 由 battle_engine.skill_available 判定技能可用性时
现场从本工厂取（传入状态条目），按角色身上状态区分（A 的封技只影响 A），与角色状态同
生命周期：状态在 filter 在，状态移除 filter 自然失效。不进内存注册表，跨回合/跨进程一致。
"""

DEFAULT_TIERS = (2, 3)


def skill_filter(eff):
    """返回技能过滤函数：状态条目 封禁品级 集合内的武学不可用（返回 False）。"""
    blocked = set(eff.get("封禁品级", DEFAULT_TIERS))
    return lambda carrying, skill: skill.get("品级") not in blocked
