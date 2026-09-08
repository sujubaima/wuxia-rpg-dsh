"""封穴 - 携带者无法使用武学及物品

无自身行为钩子。通过 filter 工厂声明两类过滤函数，与【封技】同源机制：
  - skill_filter(eff)：禁用全部武学（武学不可用，仅可休息/逃跑/认输）
  - item_filter(eff)：禁用全部物品（消耗品不可用）
两 filter 均由引擎判定技能/物品可用性时现场从本工厂取（传入状态条目），按角色身上
状态区分（A 的封穴只影响 A），与状态同生命周期：状态在 filter 在，状态移除 filter
自然失效。不进内存注册表，跨回合/跨进程一致。
"""


def skill_filter(eff):
    """封穴禁用一切武学。"""
    return lambda carrying, skill: False


def item_filter(eff):
    """封穴禁用一切物品（消耗品）。"""
    return lambda carrying, item: False
