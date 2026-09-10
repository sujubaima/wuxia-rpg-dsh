#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""title-ui 的无状态创建流程、校验与初始角色组装。"""
import copy
import random

from common import dao as dq
from store import save_manager as sm

PRIMARY_KEYS = ("内功", "力道", "身法", "根骨")
MARTIAL_KEYS = ("搏击", "剑法", "刀法", "长兵", "奇门", "暗器")
TECHNIQUE_KEYS = ("音律", "弈棋", "诗书", "绘画", "医术", "博物")
GROUPS = (
    ("一级属性", PRIMARY_KEYS, 24),
    ("武艺", MARTIAL_KEYS, 36),
    ("技艺", TECHNIQUE_KEYS, 36),
)
CAP = 12
POLAR_OPTIONS = {
    "内功": ("阴", "阳", "中"),
    "力道": ("刚", "柔", "中"),
    "身法": ("动", "静", "中"),
    "根骨": ("巧", "拙", "中"),
}
STARTER_SKILLS = (
    {"类型": "搏击", "名称": "百缠手", "门派": "丐帮", "武器": "拳套"},
    {"类型": "剑法", "名称": "太乙玄门剑", "门派": "武当派", "武器": "长剑"},
    {"类型": "刀法", "名称": "开阖刀法", "门派": "锦衣卫", "武器": "朴刀"},
    {"类型": "长兵", "名称": "夜叉棍法", "门派": "少林寺", "武器": "长棍"},
    {"类型": "暗器", "名称": "蜻蜓点水势", "门派": "乌衣门", "武器": "飞刀"},
    {"类型": "奇门", "名称": "分水刺", "门派": "峨眉派", "武器": "峨眉刺"},
)
ATTRIBUTE_HELP = (
    "内功→攻击力、内力上限；力道→暴击、精准；身法→速度、防御力；根骨→识破、气血上限。",
    "武艺六项分别增强同类武学的攻防能力。",
    "音律用于奏乐酬答；弈棋用于手谈推演；诗书用于文书典籍；绘画用于鉴画制图；医术用于诊疗辨毒；博物用于察隐采掘。",
    "阴：内力↑攻击↓；阳相反。刚：暴击↑精准↓；柔相反。动：速度↑防御↓；静相反。巧：识破↑气血↓；拙相反。中无修正。",
)


def fresh_draft():
    """返回可直接进入第二步的完整默认草稿。"""
    return {
        "名称": "",
        "性别": "男",
        "年龄": 18,
        "一级属性": {key: 6 for key in PRIMARY_KEYS},
        "极性": {key: "中" for key in PRIMARY_KEYS},
        "武艺": {key: 6 for key in MARTIAL_KEYS},
        "技艺": {key: 6 for key in TECHNIQUE_KEYS},
    }


def _as_int(value):
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value.strip())
    raise ValueError


def normalize_draft(raw=None, patch=None):
    """把往返草稿与本次 action 的局部字段合并为规范草稿。"""
    draft = fresh_draft()
    if isinstance(raw, dict):
        for key in ("名称", "性别", "年龄", "人设"):
            if key in raw:
                draft[key] = raw[key]
        for group, keys, _ in GROUPS:
            values = raw.get(group)
            if isinstance(values, dict):
                for key in keys:
                    if key in values:
                        draft[group][key] = values[key]
        values = raw.get("极性")
        if isinstance(values, dict):
            for key in PRIMARY_KEYS:
                if key in values:
                    draft["极性"][key] = values[key]
        if raw.get("初始武学") is not None:
            draft["初始武学"] = raw.get("初始武学")
    if isinstance(patch, dict):
        for key in ("名称", "性别", "年龄", "人设"):
            if key in patch:
                draft[key] = patch[key]
        for group, keys, _ in GROUPS:
            values = patch.get(group)
            if isinstance(values, dict):
                for key in keys:
                    if key in values:
                        draft[group][key] = values[key]
        values = patch.get("极性")
        if isinstance(values, dict):
            for key in PRIMARY_KEYS:
                if key in values:
                    draft["极性"][key] = values[key]
        if patch.get("初始武学") is not None:
            draft["初始武学"] = patch.get("初始武学")
    draft["名称"] = str(draft.get("名称") or "").strip()
    draft["性别"] = str(draft.get("性别") or "").strip()
    try:
        draft["年龄"] = _as_int(draft.get("年龄"))
    except (TypeError, ValueError):
        pass
    return draft


def validate_identity(draft, check_existing=True):
    name = draft.get("名称")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 12:
        return "姓名须为 1～12 个字。"
    if draft.get("性别") not in ("男", "女"):
        return "性别须为男或女。"
    try:
        age = _as_int(draft.get("年龄"))
    except (TypeError, ValueError):
        return "年龄须为整数。"
    if not 16 <= age <= 80:
        return "年龄须在 16～80 岁之间。"
    if check_existing:
        names = {str(item.get("角色名") or "").strip() for item in sm.list_all_saves()}
        if name.strip() in names:
            return f"「{name.strip()}」已有角色档，请另起一名。"
    return ""


def allocation_left(draft):
    result = {}
    for group, keys, total in GROUPS:
        try:
            used = sum(_as_int((draft.get(group) or {}).get(key)) for key in keys)
            result[group] = total - used
        except (TypeError, ValueError):
            result[group] = total
    return result


def validate_allocation(draft, exact=False):
    for group, keys, total in GROUPS:
        values = draft.get(group)
        if not isinstance(values, dict):
            return f"{group}须为完整对象。"
        used = 0
        for key in keys:
            try:
                value = _as_int(values.get(key))
            except (TypeError, ValueError):
                return f"{group}·{key}须为整数。"
            if not 0 <= value <= CAP:
                return f"{group}·{key}须在 0～{CAP} 之间。"
            values[key] = value
            used += value
        if used > total:
            return f"{group}已超出点数池 {used - total} 点。"
        if exact and used != total:
            return f"{group}尚余 {total - used} 点，须恰好分完。"
    polar = draft.get("极性")
    if not isinstance(polar, dict):
        return "极性须为完整对象。"
    for key, options in POLAR_OPTIONS.items():
        if polar.get(key) not in options:
            return f"{key}极性须为{'、'.join(options)}之一。"
    return ""


def randomize_draft(draft):
    result = copy.deepcopy(draft)
    for group, keys, total in GROUPS:
        values = {key: 0 for key in keys}
        left = total
        while left:
            candidates = [key for key in keys if values[key] < CAP]
            key = random.choice(candidates)
            values[key] += 1
            left -= 1
        result[group] = values
    result["极性"] = {key: random.choice(options) for key, options in POLAR_OPTIONS.items()}
    return result


def starter_list():
    return [dict(item) for item in STARTER_SKILLS]


def _starter(value):
    value = str(value or "").strip().strip("《》")
    return next((item for item in STARTER_SKILLS
                 if value in (item["名称"], item["类型"])), None)


def starter_detail(value):
    starter = _starter(value)
    if not starter:
        return None
    skill = dq.get("武学", starter["名称"])
    if not isinstance(skill, dict):
        return None
    detail = dict(skill)
    detail.update({
        "门派": starter["门派"],
        "武器": starter["武器"],
        "品名": {0: "凡品", 1: "上品", 2: "珍品", 3: "绝品"}.get(skill.get("品级"), str(skill.get("品级", "—"))),
        "目标范围": skill.get("目标范围") or "敌方单体",
        "特效": dq.describe_wuxue(starter["名称"], 1),
    })
    return detail


def _title_item(state, draft=None, hint="", **extra):
    item = {
        "ok": True,
        "msg": "标题操作",
        "变更": "",
        "标题状态": state,
        "版本": sm.get_version(),
        "存档列表": sm.list_all_saves(),
        "next_slot": sm.next_slot_number(),
    }
    if draft is not None:
        item["创建草稿"] = draft
        item["剩余点数"] = allocation_left(draft)
    if hint:
        item["校验提示"] = hint
    item.update(extra)
    return item


def handle_title_action(action):
    """处理 `标题-操作`，所有玩家输入错误均留在 title-ui 内提示。"""
    operation = str(action.get("操作") or "").strip()
    raw_draft = action.get("创建草稿")
    draft = normalize_draft(raw_draft, action)

    if operation in ("返回主页", "主页"):
        return _title_item("主页")
    if operation == "读档":
        return _title_item("读档")
    if operation == "开始创建":
        return _title_item("创建-立名", fresh_draft())
    if operation == "提交立名":
        error = validate_identity(draft)
        return _title_item("创建-立名" if error else "创建-资质", draft, error)
    if operation == "更新资质":
        error = validate_identity(draft) or validate_allocation(draft)
        return _title_item("创建-资质", draft, error)
    if operation == "随机分配":
        error = validate_identity(draft)
        if error:
            return _title_item("创建-资质", draft, error)
        draft = randomize_draft(draft)
        return _title_item("创建-资质", draft)
    if operation == "确认资质":
        error = validate_identity(draft) or validate_allocation(draft, exact=True)
        return _title_item("创建-资质" if error else "创建-武学", draft, error,
                           初始武学列表=starter_list())
    if operation == "属性说明":
        return _title_item("创建-资质", draft, 属性说明=list(ATTRIBUTE_HELP))
    if operation == "武学详情":
        error = validate_identity(draft) or validate_allocation(draft, exact=True)
        detail = None if error else starter_detail(action.get("武学") or action.get("名称"))
        if not error and detail is None:
            error = "请选择六门初始武学之一查看详情。"
        return _title_item("创建-武学详情" if detail else "创建-武学", draft, error,
                           初始武学列表=starter_list(), 武学详情=detail)
    if operation in ("返回武学选择", "返回武学"):
        return _title_item("创建-武学", draft, 初始武学列表=starter_list())
    if operation == "返回上一步":
        state = str(action.get("标题状态") or "")
        target = "创建-武学" if state == "创建-武学详情" else (
            "创建-资质" if state == "创建-武学" else "创建-立名")
        extra = {"初始武学列表": starter_list()} if target == "创建-武学" else {}
        return _title_item(target, draft, **extra)
    return _title_item(str(action.get("标题状态") or "主页"), draft if raw_draft else None,
                       "未知标题操作，请返回标题后重试。")


def build_character(raw_draft, skill_value):
    """把紧凑创建草稿组装成 create_slot 接受的完整角色；返回 (角色, 错误)。"""
    draft = normalize_draft(raw_draft)
    error = validate_identity(draft) or validate_allocation(draft, exact=True)
    if error:
        return None, error
    starter = _starter(skill_value or draft.get("初始武学"))
    if not starter:
        return None, "初始武学须从六门入门武学中选择。"
    name = draft["名称"]
    character = {
        "名称": name,
        "性别": draft["性别"],
        "年龄": draft["年龄"],
        "阵营": "我方",
        "武功定位": "初入江湖",
        "人设": str(draft.get("人设") or f"{name}初入江湖，来历与性情尚待江湖历练显露。"),
        "一级属性": copy.deepcopy(draft["一级属性"]),
        "极性": copy.deepcopy(draft["极性"]),
        "武艺": copy.deepcopy(draft["武艺"]),
        "技艺": copy.deepcopy(draft["技艺"]),
        "武学": [{"名称": starter["名称"], "等级": 1}],
        "携带技能": [starter["名称"]],
        "携带物品": [],
        "运转心法": None,
        "装备": {"武器1": starter["武器"], "武器2": None, "护甲": None, "饰品": None, "冠巾": None},
        "物品": [],
    }
    return character, ""
