"""存档与状态读写包:存档持久化 + go/judge/check 进程间交换文件 IO。

存档持久化(随 slot 走,save/restore 同步):
- save_manager   slot 级存档权威(explore/meta/角色文件/存档快照/merchant/overlay;字段级增量存档)
- explore_store  explore.json 字段读写的收敛入口(经 save_manager,体力夹取/位置保留等语义)
- events_store   explore.json 事件字段(任务摘要及进度)的纯数据读写/合并(经 save_manager)

进程间交换文件 IO(go/judge/check 跨进程传递,战后/读档清理,不随存档走):
- tips         tips.json(go 覆盖写变更提示,judge 读后清空)
- battle_last  battle_last.json(战斗操控 go 的结算底稿,judge 战斗-推进读回)
- battle_runtime  slot/.runtime/battle 下的战斗状态、元信息、战报路径与清理
- check_log    check.json(判定掷骰留痕,judge 按轮次核对提示带出)

功能边界:本包是所有磁盘状态读写的唯一收敛点。依赖 common.dao / common.time_utils;
被 settle / world / combat / common.check 引用。dao(数据读写层)因业务强耦合留 common,不在本包。
"""

