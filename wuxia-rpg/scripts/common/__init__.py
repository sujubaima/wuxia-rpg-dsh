"""公共共享层:被各业务包共同依赖的最底层模块。

- dao            数据读写层(角色/武学/物品/状态/阵营的 JSON 读写 + 角色派生 + 写时复制 + 缓存)
- effect_loader  动态特效脚本加载库(effects/{status,skills,equipments} 三类 .py 的 importlib 加载,带缓存)
- status_manager 状态管理(施加/清理/计时/钩子;战斗与大世界共用,靠注入保持 sm 不依赖战斗)
- check         统一判定脚本(掷骰 + 留痕;战斗逃跑/大世界技艺判定经此)
- time_utils     时间换算(数字时刻 ↔ 中文时辰字符串/时段)

功能边界:本层依赖仅限标准库 + 包内互相引用(dao→effect_loader, status_manager→dao/effect_loader,
check→dao/save_manager),不依赖任何业务包——是被依赖方,处于依赖链最底层。
dao 因与角色派生/缓存全局态强耦合,保持整体不进一步拆分。
"""

