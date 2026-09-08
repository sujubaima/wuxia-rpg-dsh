"""装备效果脚本接口定义

每件物品的「装备效果」字段为 {effect_id: params}（统一字段，涵盖属性加成与
特殊特效），其中 effect_id 对应 equipment_effects/ 目录下一个同名 Python 文件
（如 attr_bonus.py、rest_recover_mult.py），params（标量或 dict）随钩子透传给脚本。

引擎通过两套统一机制消费装备效果，均基于 equipped_items() + load_equipment_effect()：

1. 平坦加成（build 时一次性施加，幂等）
   - collect_equipment_bonuses(actor) 汇总各脚本的 flat_bonuses(actor, params) 钩子
     返回值（{stat: delta}，按属性求和），再由 apply_equipment_bonuses 施加到角色
     武艺/二级属性。
2. 触发式钩子（结算点串联改写）
   - apply_equipment_hook(actor, hook_name, value) 依次调用各脚本的 hook_name(value, params)。

未装备效果、脚本缺失、或脚本未实现相应钩子的，一律跳过。

钩子约定（按需实现）：
- flat_bonuses(actor, params) -> {stat: delta}
    汇总平坦属性加成。stat 可为武艺（剑法 等）或二级属性（攻击力 等）。
- modify_rest_recover(actor, recover, params) -> (hp, mp)
    休息恢复结算时调用，recover 为 (气血恢复量, 内力恢复量)。

内置 effect_id：
- attr_bonus           平坦属性加成（params = {stat: delta}，如 {"剑法": 1}）
- attr_mult            百分比属性加成（params = {stat: 百分数}，如 {"内力上限": 10} 表 +10%；按二级属性当前值折算为平坦加成）
- rest_recover_mult    休息恢复倍率（params = {"气血": mult, "内力": mult}，如 {"内力": 2}）

新增装备机制时：加一个 effect_id 脚本实现对应钩子，并在该机制的结算点调用
apply_equipment_hook（触发式）或在 flat_bonuses 中返回（加成式）即可，无需改主流程。
"""
