#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine 共享事务态。

集中持有 settle 期间的三个可变全局，作为多模块共同 import 的公共容器。
拆分后各模块用 `engine_state._TXN = {}` 属性赋值代替 `global _TXN` 声明
（global 仅在本模块内有效，跨文件须靠本容器的属性读写）。
"""

# 事务暂存区：settle 校验阶段暂存各类改动，全过才统一刷盘，任一失败整体回滚不落盘
_TXN = None  # {角色名: char}；已有角色更新
_NEW_CHAR_STAGED = None  # {角色名: char}；本轮新建角色，commit 时才 write_character
_SCENE_STAGED = None  # 本轮场景登记暂存区 {区域:{场景:{方位:邻}}}
_SCENE_TYPE_STAGED = None  # 本轮场景类型暂存区 {区域:{场景:类型}}
_MERCHANT_STAGED = None  # merchant.json 的本轮工作副本（延迟加载）
_MERCHANT_DIRTY = False
_SESSION = None  # 当前 SettlementSession；供 action adapter 提交 mutation
