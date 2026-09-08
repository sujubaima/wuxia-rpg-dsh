#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一判定脚本 —— 大世界所有技艺/属性判定经此掷骰，数字隔离（仅返回成功/失败）。

公式（与 exploration.md「判定系统」同源）：
  最终成功率 = clamp(基础成功率 + (判定值 − 对抗等级) × 10%, 5%, 95%)
  掷 1~100 ≤ 最终成功率 即成功。

用法：
  python3 scripts/check.py <属性> <判定角色> <对抗角色|@数值> <基础成功率> [--slot <N>]
  python3 scripts/check.py random-event [基础触发率]

参数（属性判定）：
  <属性>           判定属性名，技艺或一级属性。多属性用逗号分隔，取平均值
                   （如 "身法,根骨"）。角色与对抗方各自按同名属性集取均值。
  <判定角色>       进行判定的角色名，可逗号分隔多个（如 "陈挺之,骆逸"），
                   多角色各自按属性集取值后再取均值。
  <对抗角色|@数值> 对抗方：角色名（可逗号多个，同判定角色取均值）作对抗等级；
                   以 @ 开头则后接数值直接作对抗等级（如 @15）。
  <基础成功率>     0~100 整数，GM 据难度拟定，直接传入。
  --slot <N>       存档槽号（正式游戏读 slot 的 .data/，调试读 assets/data/）。
                   传入时，掷骰记录自动追加到该 slot 的 check.json（轮次从
                   explore.json 读取，供 judge 按轮次核对判定是否执行/带提示）；
                   不传则不落盘。

random-event 子接口：移动时判断是否触发随机事件。基础触发率缺省 15，
                     可传 0~100 整数覆盖（天气/区域等情境调整）。

返回：
  属性判定  → {"结果": "成功"|"失败", "提示": "<属性>判定{成功|失败}"}
  随机事件  → {"结果": "触发"|"未触发", "提示": "随机事件{触发|未触发}"}
成功率/掷骰数等仅在内部计算，不外泄；提示字段可直接呈现给玩家。
"""

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from common import dao as dq

# 支持的判定属性：技艺 + 一级属性（不含武艺）
_VALID_ATTRS = {
    "音律", "弈棋", "诗书", "绘画", "医术", "博物",  # 技艺
    "内功", "力道", "身法", "根骨",  # 一级属性
}

def _attr_value(char, attrs):
    """取角色在一组属性上的均值。char 为角色记录 dict；attrs 为属性名列表。

    从「一级属性」或「技艺」字段取值；属性缺失记 0。空属性集视为 0。
    """
    if not attrs:
        return 0
    prim = char.get("一级属性") or {}
    art = char.get("技艺") or {}
    vals = []
    for a in attrs:
        if a in prim:
            vals.append(prim[a])
        elif a in art:
            vals.append(art[a])
        else:
            vals.append(0)
    return sum(vals) / len(vals) if vals else 0

def _decide(judge_val, oppose_level, base_rate):
    """纯掷骰判定：返回 (成功: bool, 最终成功率: float, 掷骰: int)。

    最终成功率 = clamp(base_rate + (judge_val − oppose_level) × 10, 5, 95)；
    掷 1~100 ≤ 最终成功率即成功。供内部组合调用（如战斗逃跑经本函数掷骰）。
    """
    rate = max(5, min(95, base_rate + (judge_val - oppose_level) * 10))
    roll = random.randint(1, 100)
    return roll <= rate, rate, roll

def run_check(attrs, judge_names, opponent, base_rate, data_dir=None,
              char_lookup=None):
    """执行一次判定，返回 {"结果": "成功"|"失败"}。

    attrs：属性名列表（已拆分）；judge_names：判定角色名列表（多角色取均值）；
    opponent：对抗角色名（可逗号多个）或以 @ 开头的数值字符串 或 None；
    base_rate：基础成功率（0~100）；data_dir：可选数据目录；
    char_lookup：可选的角色查表函数 name→dict，缺省经 dq.get("角色", name, data_dir)
    （战斗等场景可传入内存中的角色记录，免落盘读取、用实时战斗属性）。
    """
    # 校验属性
    bad = [a for a in attrs if a not in _VALID_ATTRS]
    if bad:
        return {"错误": f"非法判定属性：{'、'.join(bad)}。可用：{'、'.join(sorted(_VALID_ATTRS))}"}

    def _lookup(nm):
        if char_lookup is not None:
            return char_lookup(nm)
        return dq.get("角色", nm, data_dir)

    if not judge_names:
        return {"错误": "须指定判定角色"}
    judge_vals = []
    for nm in judge_names:
        char = _lookup(nm)
        if char is None:
            return {"错误": f"未找到判定角色【{nm}】"}
        judge_vals.append(_attr_value(char, attrs))
    judge_val = sum(judge_vals) / len(judge_vals)

    # 对抗等级
    if opponent is None or opponent == "":
        return {"错误": "须指定对抗角色或以 @数值 形式给出对抗等级"}
    if opponent.startswith("@"):
        try:
            oppose_level = float(opponent[1:])
        except ValueError:
            return {"错误": f"对抗数值非法：{opponent}"}
    else:
        opp_names = [o.strip() for o in opponent.split(",") if o.strip()]
        opp_vals = []
        for nm in opp_names:
            char = _lookup(nm)
            if char is None:
                return {"错误": f"未找到对抗角色【{nm}】"}
            opp_vals.append(_attr_value(char, attrs))
        oppose_level = sum(opp_vals) / len(opp_vals) if opp_vals else 0

    try:
        base = int(base_rate)
    except (TypeError, ValueError):
        return {"错误": f"基础成功率须为 0~100 整数：{base_rate}"}

    success, rate, roll = _decide(judge_val, oppose_level, base)
    result = "成功" if success else "失败"
    return {"结果": result,
            "提示": f"属性（{'、'.join(attrs)}）判定{result}"}

def run_random_event(base_rate=15):
    """掷骰判断是否触发随机事件。base_rate 为基础触发率（0~100，缺省 15）。
    掷 1~100 ≤ base_rate 即触发。返回 {"结果":"触发"|"未触发","提示":...}，
    概率/掷骰仅在内部，不外泄。
    """
    try:
        rate = int(base_rate)
    except (TypeError, ValueError):
        return {"错误": f"基础触发率须为 0~100 整数：{base_rate}"}
    rate = max(0, min(100, rate))
    roll = random.randint(1, 100)
    triggered = roll <= rate
    result = "触发" if triggered else "未触发"
    return {"结果": result, "提示": f"随机事件{result}"}

# ----------------------------- CLI -----------------------------
# check 的命令行入口已并入 engine.py 的 `check` 子命令（stdin JSON 传参）。
# 本模块仅保留 run_check / run_random_event 供 engine 与 wuxia_check 工具复用。
