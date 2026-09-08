#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine 共享事务态。

集中持有 settle 期间的三个可变全局，作为多模块共同 import 的公共容器。
拆分后各模块用 `engine_state._TXN = {}` 属性赋值代替 `global _TXN` 声明
（global 仅在本模块内有效，跨文件须靠本容器的属性读写）。
"""

# 事务暂存区：settle 校验阶段暂存各角色改动，全过才一次性刷盘，任一失败整体回滚不落盘
_TXN = None  # {角色名: char} 或 None（非事务态）；settle 期间置 {}，_write_char 仅暂存，commit 时统一刷盘
_SCENE_STAGED = None  # 本轮场景登记暂存区 {区域:{场景:{方位:邻}}}，commit 阶段落盘；None=非事务态
_SCENE_TYPE_STAGED = None  # 本轮场景类型暂存区 {区域:{场景:类型}}，commit 阶段落盘；None=非事务态
