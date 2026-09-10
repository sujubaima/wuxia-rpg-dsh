#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""渲染模式归一解析。

WUXIA_RPG_RENDER_MODULE 取值（大小写不敏感）：dsh / WEB_UI / LLM。
未设置或空白统一按 LLM 处理；比较时一律先经 render_mode() 归一，
消除「响应里渲染模式是空串、内部分支却按 LLM 取数」的不一致。
"""
import os


def render_mode(env=None):
    """归一渲染模式：未设置/空白 → LLM；其余去首尾空白原样返回。"""
    val = (env if env is not None else os.environ).get("WUXIA_RPG_RENDER_MODULE")
    return (val or "").strip() or "LLM"


def is_dsh_mode(env=None):
    """是否 dsh 渲染模式（前端卡片直接消费结构化字段）。"""
    return render_mode(env).lower() == "dsh"
