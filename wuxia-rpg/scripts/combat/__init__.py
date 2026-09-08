"""战斗包:战斗的入口、引擎、AI 决策与评分。

- battle         战斗入口 + 三层战报渲染器；运行态经 store.battle_runtime 按 slot 隔离
- battle_engine  战斗引擎核心(接受战场状态/指令 → 输出结果与新状态)
- ai_styles      AI 战斗风格策略集(平衡/勇猛/谨慎),据角色「战斗风格」字段分发
- skill_scorer   AI 技能评分器(综合威力/特效/识破/内耗,供 ai_styles 加权选技)

功能边界:本包是自洽的战斗簇,内部依赖闭合(battle → battle_engine → ai_styles → skill_scorer;
battle_engine 同时依赖 common.status_manager)。战斗与大世界共用 common.status_manager(留 common,
不在本包)。战后气血/内力/物品消耗由 battle 自落盘,经验/处决/战利品经 settle.judge 状态变更落盘。
战斗运行态文件位于 slot 的 .runtime/battle，不随 save/restore 走。
"""

