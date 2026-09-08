"""技能特效脚本接口。

武学数据以「技能特效」引用本目录脚本。战斗钩子统一签名为
`on_xxx(source, ctx)`，可按需实现：

- on_action：整次行动一次，适合自施效果。
- on_target_check：闪避判定前，可改写精准、闪避率或设置必中。
- on_target_confirmed：目标确认未闪避后。
- on_damage_calc：基础伤害与暴击计算后、落账前。
- on_settle / on_before_commit：普通结算改写 / 最终写池前改写。
- on_target_resolved：目标落账且仍在场后，敌方全体逐目标调用。

`ctx`提供行动者、原目标/实际目标、行动、事件、结果、角色列表、识破结果，及
`apply_status`、`settle`回调。技能特效受识破门控，状态钩子不受其影响；「独立」
在每个未闪避目标上掷一次并供该目标后续阶段复用。

脚本可声明 EFFECT_STATUS、EFFECT_DURATION、EFFECT_TARGET、EFFECT_STACKS、EFFECT_MECHANIC
供说明生成使用。
"""
