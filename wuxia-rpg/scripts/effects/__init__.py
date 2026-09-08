"""状态特效脚本接口。

战斗阶段统一使用 `on_xxx(source, ctx)`：
- on_action：行动成立后，每次行动一次。
- on_target_check：每目标闪避判定前。
- on_target_confirmed：目标未闪避后。
- on_damage_calc：基础伤害与暴击计算后。
- on_settle：气血/内力结算改写。
- on_before_commit：最终写池前。
- on_target_resolved：目标落账且仍在场后。

每阶段先执行当前技能/物品特效，再执行阶段开始时快照的全场状态。同一持有者的
同一状态ID聚合为一个 source，`source["条目"]`为有效条目，`source["层数"]`为层数。
状态钩子自行判断与当前事件的关系，无关时直接返回。

保留专用接口：
- 生命周期：on_apply(char, eff)、on_removed(char)
- 回合：on_turn_start/on_turn_end(char, characters)
- 查询改写：on_modify_attr、on_modify_mp_cost、on_modify_cooldown、on_weapon_check
- 拦截与过滤：on_action_blocked、status_filter、skill_filter、item_filter、target_filter
"""
