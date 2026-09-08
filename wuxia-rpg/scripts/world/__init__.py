"""大世界业务层包:大世界侧的字段变更、物品交易、事件、武学精进、场景图等业务。

- character_ops 角色纯字段变更业务逻辑(铜钱/经验/关系度/气血/内力/技艺/心法/携带技能/在队)
- loadout      物品/装备/携带物品业务逻辑(背包增减/装备穿脱/携带配置)
- trade        交易辅助(卖家可售物品列表)
- event        事件系统业务视图层 + CLI(进行中/已关闭/精简/全貌查询;数据读写下沉 store.events_store)
- mastery      武学精进(十境)引擎(展示十境表/执行精进/秘籍习得)
- scene        区域场景图(基线 scenes.json + per-slot 覆盖层;登记/隔离/寻路/渲染)
- map          大世界区域拓扑寻路(BFS)
- map_query     GM 侧场景图查询工具(CLI)

功能边界:业务逻辑纯函数居多,就地改角色 dict,不直接落盘——落盘经 store.save_manager。
依赖 common.dao / store.save_manager;被 settle(大世界结算)引用。event 的底层读写经 store.events_store,
scene 的 overlay 读写经 store.save_manager(本包为权威读写者,save_manager 仅同步镜像)。
"""

