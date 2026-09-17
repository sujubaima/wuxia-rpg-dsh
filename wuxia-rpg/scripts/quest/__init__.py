"""任务状态机包:线索蓝图、事实条件归约、奖励结算、提示与触发器。

- events      结算领域事件协议(类型词汇表/DomainEvent/EventFactory/EventCodecV1),事件泵唯一消费方为本包
- world_facts 槽位级规范世界事实(定义、类型、互斥与受控写入)
- conditions  任务条件受限 DSL(求值/事实引用/校验)
- models      任务蓝图与运行时状态的规范化模型 + legacy 导入
- projection  任务运行状态到旧线索栏结构及结算摘要的投影
- registry    同步领域事件触发器注册表(TriggerRegistry/TriggerOutcome)
- validator   蓝图结构、可达性、事实覆盖与跨任务冲突校验
- engine      事实驱动的任务图创建、扩展、发现与固定点归约
- triggers    机械事件→规范事实、事实→任务归约及 GM 候选提示

依赖方向(单向自底向上,无环):
triggers → engine → validator/conditions/models/world_facts → events(协议层,仅 stdlib)
本包不依赖 settle/world/store/combat 任何模块;settle(settlement/engine_actions)与
engine.py 单向引用本包,不存在任何形式的循环导入。
"""
