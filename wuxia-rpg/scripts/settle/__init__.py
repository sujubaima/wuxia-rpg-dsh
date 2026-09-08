"""engine 结算层包:engine.py 的 go/judge 两步式结算内部实现。

engine.py 仅留顶层入口(go/judge/CLI + 主流程编排),本包是其按职责拆分的五层:
- engine_state  共享事务态(_TXN/_SCENE_STAGED,多模块公共容器,代替跨文件 global)
- engine_io     存档读写与状态快照(_read_char/_write_char 事务态、_build_state、地图、战斗底稿清理)
- engine_fields 字段变更原语(_chg_* + _FIELD_HANDLERS,judge 状态变更条目落盘的零件库)
- engine_ui     界面数据构建(_build_*/merchant_*/_UI_BUILDERS,纯取数拼装,无结算无落盘)
- engine_actions go 的 action 处理器(_act_* + _ACTION_HANDLERS + 计费常量)

依赖方向(单向自底向上,无环):
engine.py → engine_actions → engine_fields/engine_ui → engine_io → engine_state
分发表跟随其函数所在层:_FIELD_HANDLERS 在 fields、_ACTION_HANDLERS 在 actions、_UI_BUILDERS 在 ui。
本包依赖 store(存档)/world(业务)/common(dao/status_manager)/combat(battle),不被这些包反向依赖。
"""

