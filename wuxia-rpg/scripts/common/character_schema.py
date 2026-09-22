#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""角色记录严格校验：创建角色 / 写角色 的完整 dict 入口统一把关。

基线 119 个预设角色字段完全统一，本模块按同一 schema 校验 GM 手写 dict：
必填字段齐全、键名精确（拦截「同级极性」「年岁」这类误名字段）、值域合法、
派生字段（二级属性/气血/内力）不得传入。校验只在引擎入口做，
dao 写入层与读档恢复不做（旧档兼容）。
"""

PRIMARY_KEYS = ("内功", "力道", "身法", "根骨")
MARTIAL_KEYS = ("搏击", "剑法", "刀法", "长兵", "奇门", "暗器")
TECHNIQUE_KEYS = ("音律", "弈棋", "诗书", "绘画", "医术", "博物")
POLAR_OPTIONS = {
    "内功": ("阴", "阳", "中"),
    "力道": ("刚", "柔", "中"),
    "身法": ("动", "静", "中"),
    "根骨": ("巧", "拙", "中"),
}
EQUIP_KEYS = ("武器1", "武器2", "护甲", "饰品", "冠巾")
COMBAT_STYLES = ("平衡", "勇猛", "谨慎")

# 必填（缺一打回），与 data-schema「创建角色/写临时 NPC 模板」一致
REQUIRED = ("名称", "性别", "年龄", "阵营", "一级属性", "极性", "武艺", "技艺", "武学", "人设")
# 可选字段（出现时校验类型与值域）；id 为引擎内部字段
OPTIONAL = ("经验值", "铜钱", "关系度", "死亡", "运转心法", "携带技能", "携带物品",
            "装备", "物品", "战斗风格", "持久化", "武功定位", "id")
# 由 engine 从一级属性/极性/武学/装备派生，创建/写入时不得传入
DERIVED = ("二级属性", "气血", "内力", "气血上限", "内力上限")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_pool(values, label, keys, cap=None):
    if not isinstance(values, dict) or set(values) != set(keys):
        return f"{label}须且仅须含 {'、'.join(keys)}"
    for key in keys:
        value = values[key]
        if not _is_int(value) or value < 0 or (cap is not None and value > cap):
            bound = f"0～{cap}" if cap is not None else "非负"
            return f"{label}·{key}须为{bound}整数"
    return None


def validate_character_record(char, skill_lookup=None, item_lookup=None):
    """校验完整角色 dict；合法返回 None，否则返回首条错误说明。

    skill_lookup / item_lookup：名称→记录（或 None）的查表函数，引擎侧传 dao.get；
    缺省跳过武学、心法与装备的存在性校验（仅校结构）。
    """
    if not isinstance(char, dict):
        return "角色须为对象"
    name = char.get("名称")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 12:
        return "名称须为 1～12 个字"

    unknown = [k for k in char if k not in REQUIRED + OPTIONAL + DERIVED]
    if unknown:
        return (f"存在未知字段：{'、'.join(unknown)}"
                "——字段名须与 data-schema 模板一致，疑似拼写错误")
    derived = [k for k in DERIVED if k in char]
    if derived:
        return f"{'、'.join(derived)} 由 engine 派生，创建/写入时不传"
    missing = [k for k in REQUIRED if k not in char]
    if missing:
        return f"缺少必填字段：{'、'.join(missing)}"

    if char.get("性别") not in ("男", "女"):
        return "性别须为男或女"
    if not _is_int(char.get("年龄")) or not 1 <= char["年龄"] <= 120:
        return "年龄须为 1～120 的整数"
    if not isinstance(char.get("阵营"), str) or not char["阵营"].strip():
        return "阵营须为非空字符串"

    err = _check_pool(char.get("一级属性"), "一级属性", PRIMARY_KEYS)
    if err:
        return err
    polar = char.get("极性")
    if not isinstance(polar, dict) or set(polar) != set(PRIMARY_KEYS):
        return f"极性须且仅须含 {'、'.join(PRIMARY_KEYS)}（「同级极性」为无效字段名）"
    for key, options in POLAR_OPTIONS.items():
        if polar.get(key) not in options:
            return f"极性·{key}须为{'、'.join(options)}之一"

    err = _check_pool(char.get("武艺"), "武艺", MARTIAL_KEYS, cap=25)
    if err:
        return err
    err = _check_pool(char.get("技艺"), "技艺", TECHNIQUE_KEYS, cap=25)
    if err:
        return err

    wuxue = char.get("武学")
    if not isinstance(wuxue, list) or not wuxue:
        return "武学须为非空数组 [{名称, 等级}]"
    known = set()
    for i, w in enumerate(wuxue):
        if (not isinstance(w, dict) or not isinstance(w.get("名称"), str)
                or not w["名称"].strip()):
            return f"武学[{i}] 须为 {{名称, 等级}} 对象且名称非空"
        skill = w["名称"].strip()
        if not _is_int(w.get("等级")) or not 1 <= w["等级"] <= 10:
            return f"武学【{skill}】等级须为 1～10 整数"
        known.add(skill)
        if skill_lookup is not None and skill_lookup(skill) is None:
            return f"武学【{skill}】不存在，须为武学库已收录名称"

    if not isinstance(char.get("人设"), str) or not char["人设"].strip():
        return "人设须为非空字符串"

    for field in ("经验值", "铜钱"):
        if field in char and (not _is_num(char[field]) or char[field] < 0):
            return f"{field}须为非负数值"
    if "关系度" in char and (not _is_int(char["关系度"])
                            or not 0 <= char["关系度"] <= 100):
        return "关系度须为 0～100 整数"
    for field in ("死亡", "持久化"):
        if field in char and not isinstance(char[field], bool):
            return f"{field}须为布尔值"
    if "战斗风格" in char and char["战斗风格"] not in COMBAT_STYLES:
        return f"战斗风格须为{'、'.join(COMBAT_STYLES)}之一"
    if "武功定位" in char and not (isinstance(char["武功定位"], str)
                                   and char["武功定位"].strip()):
        return "武功定位须为非空字符串"
    if "运转心法" in char and char["运转心法"] is not None:
        xinfa = char["运转心法"]
        if not isinstance(xinfa, str) or not xinfa.strip():
            return "运转心法须为武学名称或 null"
        if skill_lookup is not None and skill_lookup(xinfa.strip()) is None:
            return f"运转心法【{xinfa}】不存在，须为武学库已收录名称"

    if "携带技能" in char:
        carried = char["携带技能"]
        if (not isinstance(carried, list) or len(carried) > 4
                or any(not isinstance(s, str) or not s.strip() for s in carried)):
            return "携带技能须为武学名称数组，最多4门"
        outside = [s for s in carried if s.strip() not in known]
        if outside:
            return f"携带技能须为已习得武学：{'、'.join(outside)}"
    if "携带物品" in char:
        carried = char["携带物品"]
        if (not isinstance(carried, list) or len(carried) > 4
                or any(not isinstance(s, str) or not s.strip() for s in carried)):
            return "携带物品须为物品名称数组，最多4类"
    if "物品" in char:
        if (not isinstance(char["物品"], list)
                or any(not isinstance(s, str) or not s.strip() for s in char["物品"])):
            return "物品须为字符串数组"
    if "装备" in char:
        equip = char["装备"]
        if not isinstance(equip, dict):
            return "装备须为对象"
        extra = [k for k in equip if k not in EQUIP_KEYS]
        if extra:
            return f"装备键须为 {'、'.join(EQUIP_KEYS)}：多余键 {'、'.join(extra)}"
        for slot_key, value in equip.items():
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                return f"装备·{slot_key}须为物品名称或 null"
            if item_lookup is not None and item_lookup(value.strip()) is None:
                return f"装备【{value}】不存在，须为物品库已收录名称"
    return None
