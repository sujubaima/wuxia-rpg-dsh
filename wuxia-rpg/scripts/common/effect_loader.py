#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态特效脚本加载库——状态、技能、物品、装备脚本的统一加载入口。

引擎最基础层：仅依赖标准库（importlib），被 dao 与 battle_engine 共同依赖。
每类脚本独立缓存，按目录和名称定位，缺失返回 None。
脚本位于引擎目录（与存档 slot 无关），故缓存常驻、无需随 set_data_dir 失效，dao 与 battle_engine 共享同一缓存实例。
"""
import os
import importlib.util

_ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/（effects 目录所在）
_DIRS = {
    "effect": os.path.join(_ENGINE_DIR, "effects", "status"),
    "skill_effect": os.path.join(_ENGINE_DIR, "effects", "skills"),
    "item_effect": os.path.join(_ENGINE_DIR, "effects", "items"),
    "equipment_effect": os.path.join(_ENGINE_DIR, "effects", "equipments"),
}
_caches = {key: {} for key in _DIRS}


def load_script(category, name):
    """加载 <category 对应目录>/<name>.py 脚本模块（带缓存）；文件缺失返回 None。"""
    cache = _caches[category]
    if name in cache:
        return cache[name]
    path = os.path.join(_DIRS[category], f"{name}.py")
    mod = None
    if os.path.exists(path):
        spec = importlib.util.spec_from_file_location(f"{category}.{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    cache[name] = mod
    return mod


def load_effect(name):
    """动态加载 effects/status/<name>.py 状态脚本。"""
    return load_script("effect", name)


def load_skill_effect(name):
    """动态加载 effects/skills/<name>.py 技能特效脚本。"""
    return load_script("skill_effect", name)


def load_item_effect(name):
    """动态加载 effects/items/<name>.py 物品特效脚本模块。"""
    return load_script("item_effect", name)


def load_equipment_effect(name):
    """动态加载 effects/equipments/<name>.py 装备特效脚本。"""
    return load_script("equipment_effect", name)


# ----------------------------- 特效加成折算 -----------------------------
# 武学十境里的特效持续时间、层数加成按当前等级筛十境条目求和。
# 供 skill 特效脚本自助应用（引擎不再自动注入/应用）。与 dao._eff_* 同源。

def _eff_applicable(skill, level):
    """等级≤level 的十境条目（稠密/稀疏表兼容）。"""
    level = max(1, level or 1)
    return [e for e in skill.get("等级增益", [])
            if isinstance(e, dict) and e.get("等级", 1) <= level]


def effect_dur_bonus(skill):
    """该武学当前等级下「特效持续时间」加成总和（供 skill 特效脚本加到施加时长）。"""
    level = skill.get("_等级", 1)
    return sum(e.get("效果", {}).get("特效持续时间", 0) for e in _eff_applicable(skill, level))


def effect_stack_bonus(skill):
    """该武学当前等级下「特效层数」加成总和（供 skill 特效脚本叠加到 EFFECT_STACKS）。"""
    level = skill.get("_等级", 1)
    return sum(e.get("效果", {}).get("特效层数", 0) for e in _eff_applicable(skill, level))
