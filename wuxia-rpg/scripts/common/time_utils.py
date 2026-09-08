# -*- coding: utf-8 -*-
"""通用工具：时间换算。

时间以数字记录（0 起）：1 刻 = 15 分钟，1 天 = 96 刻；
1 月 = 30 天，1 年 = 12 月 = 360 天。unit 0 = 第一年一月一日子时初刻。
"""

_ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]  # 十二时辰
_KE = ["初", "一", "二", "三", "四", "五", "六", "七"]                          # 时辰内 0~7 刻
_CN_DIGIT = "零一二三四五六七八九"

TIME_UNITS_PER_DAY = 96
UNITS_PER_ZHI = 8
DAYS_PER_MONTH = 30
MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = DAYS_PER_MONTH * MONTHS_PER_YEAR  # 360

# 时辰 → 时段（清晨/白天/傍晚/夜晚），索引对应 _ZHI 顺序
_ZHI_SLOT = {
    0: "夜晚",   # 子
    1: "夜晚",   # 丑
    2: "夜晚",   # 寅
    3: "清晨",   # 卯
    4: "白天",   # 辰
    5: "白天",   # 巳
    6: "白天",   # 午
    7: "白天",   # 未
    8: "白天",   # 申
    9: "傍晚",   # 酉
    10: "夜晚",  # 戌
    11: "夜晚",  # 亥
}


def _cn_num(n):
    """正整数 → 中文数字（1~9999）。"""
    if n <= 0:
        return "零"
    if n < 10:
        return _CN_DIGIT[n]
    if n < 20:
        return "十" + (_CN_DIGIT[n - 10] if n > 10 else "")
    if n < 100:
        return _CN_DIGIT[n // 10] + "十" + (_CN_DIGIT[n % 10] if n % 10 else "")
    if n < 1000:
        head = _CN_DIGIT[n // 100] + "百"
        rest = n % 100
        if rest == 0:
            return head
        if rest < 10:
            return head + "零" + _CN_DIGIT[rest]
        if rest < 20:
            return head + "一十" + (_CN_DIGIT[rest - 10] if rest > 10 else "")
        return head + _cn_num(rest)
    head = _CN_DIGIT[n // 1000] + "千"
    rest = n % 1000
    if rest == 0:
        return head
    if rest < 100:
        if rest < 10:
            return head + "零" + _CN_DIGIT[rest]
        if rest < 20:
            return head + "一十" + (_CN_DIGIT[rest - 10] if rest > 10 else "")
        return head + "零" + _cn_num(rest)
    return head + _cn_num(rest)


def time_to_str(n):
    """数字时刻 → 第X年X月X日时辰制字符串（如 "第一年 一月一日 卯时三刻"）。"""
    n = int(n)
    day_index = n // TIME_UNITS_PER_DAY
    h = n % TIME_UNITS_PER_DAY
    year = day_index // DAYS_PER_YEAR + 1
    month = day_index % DAYS_PER_YEAR // DAYS_PER_MONTH + 1
    day = day_index % DAYS_PER_MONTH + 1
    return (f"第{_cn_num(year)}年 {_cn_num(month)}月{_cn_num(day)}日 "
            f"{_ZHI[h // UNITS_PER_ZHI]}时{_KE[h % UNITS_PER_ZHI]}刻")


def time_slot_of(n):
    """数字时刻 → 时段（清晨/白天/傍晚/夜晚）。"""
    h = int(n) % TIME_UNITS_PER_DAY
    return _ZHI_SLOT[h // UNITS_PER_ZHI]
