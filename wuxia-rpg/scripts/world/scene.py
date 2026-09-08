#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""区域内场景图模块：基线 scenes.json + per-slot 覆盖层 map_overlay.json。

数据组织（assets/data/scenes.json）：
- 上限：{区域: 该区域场景总量上限}（含基线场景）。未列区域兜底 _SCENE_DEFAULT_LIMIT。
- 驿站出口：{区域: 出城所经驿站场景名}。
- 场景：{区域: {场景: {方位: 邻场景}}}，方位取 北/东北/东/东南/南/西南/西/西北。

覆盖层（save/slot_{N}/map_overlay.json）：GM 运行时新增的场景，随存档 save/restore 同步。
结构同基线「场景」一层：{区域: {场景: {方位: 邻场景}}}。引擎写时自动补反向边。
渲染取 基线 ∪ 覆盖层。

暴露给 engine：
- build_map(slot, action, explore, resolve_region, station_type) → map-ui 数据
  （邻接图 + 已知地点清单 + 驿站出口）
- register_scene(slot, action, staged) → 登记场景（随剧情推动状态变更「登记场景」带入，
  自动补反向边，达上限拒绝；写入内存暂存区，commit_staged 落盘以支持整轮回滚）
- commit_staged(slot, staged) → 整轮通过后把暂存登记合并落盘
- overlay 同步钩子（save/restore 用）：read_overlay / write_overlay
"""
import os
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from common.json_io import read_json
from store import save_manager as sm

_SCENES_PATH = os.path.join(HERE, "..", "assets", "data", "scenes.json")
_SCENE_DEFAULT_LIMIT = 16  # 未在 scenes.json 上限表中的区域兜底上限
# 场景邻接方位及反向映射（登记场景时自动补反向边）
_SCENE_DIR_REVERSE = {"北": "南", "南": "北", "东": "西", "西": "东",
                     "东北": "西南", "西南": "东北", "东南": "西北", "西北": "东南"}
# 八方位顺序（邻接图按此排序方向）
_COMPASS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
COMPASS_ORDER = _COMPASS  # 公开别名，供 engine 取方位顺序


def load_scenes():
    """严格读取 scenes.json 基线场景数据。"""
    return read_json(_SCENES_PATH, expected_type=dict)


def overlay_path(slot):
    """GM 运行时新增场景覆盖层路径：save/slot_{N}/map_overlay.json。"""
    return os.path.join(sm.slot_path(slot), sm.MAP_OVERLAY_FILENAME)


def read_overlay(slot):
    """读取 slot 覆盖层；缺失/损坏返回 {}。结构 {区域:{场景:{方位:邻场景}}}。"""
    return sm.read_map_overlay(slot)


def write_overlay(slot, data):
    """写 slot 覆盖层；data 为空时删除文件以保持整洁。"""
    sm.write_map_overlay(slot, data)


def read_type_overlay(slot):
    """读取 slot 场景类型覆盖层；缺失/损坏返回 {}。结构 {区域:{场景:类型}}。"""
    return sm.read_scene_types_overlay(slot)


def write_type_overlay(slot, data):
    """写 slot 场景类型覆盖层；data 为空时删除文件以保持整洁。"""
    sm.write_scene_types_overlay(slot, data)


# 场景功能类型取值（基线 场景类型 表 ∪ 覆盖层）
_SCENE_TYPES = {"驿站", "店铺", "客栈"}


def _type_entry(val):
    """场景类型表的一项 → (类型, 功能NPC)。兼容两种形态：
    字符串 "店铺"（旧）→ ("店铺", None)；对象 {类型, 功能NPC}（新）→ (类型, 功能NPC)。"""
    if isinstance(val, str):
        return val, None
    if isinstance(val, dict):
        return val.get("类型"), val.get("功能NPC")
    return None, None


def scene_type(slot, region, scene, scenes=None):
    """取某场景的功能类型（基线 场景类型 ∪ 覆盖层）。无类型/不存在返回 None。"""
    if not region or not scene:
        return None
    scenes = scenes if scenes is not None else load_scenes()
    base_types = (scenes.get("场景类型", {}) or {}).get(region, {})
    if isinstance(base_types, dict) and scene in base_types:
        return _type_entry(base_types[scene])[0]
    ov = read_type_overlay(slot).get(region, {})
    if isinstance(ov, dict) and scene in ov:
        return _type_entry(ov[scene])[0]
    return None


def scene_npc(slot, region, scene, scenes=None):
    """取某场景的功能NPC名（基线 ∪ 覆盖层）。无/不存在返回 None。
    功能NPC名仅为身份标签，不等于落盘角色——多数驿丞/掌柜不落盘，只在场景要素露脸。"""
    if not region or not scene:
        return None
    scenes = scenes if scenes is not None else load_scenes()
    base_types = (scenes.get("场景类型", {}) or {}).get(region, {})
    if isinstance(base_types, dict) and scene in base_types:
        npc = _type_entry(base_types[scene])[1]
        if npc:
            return npc
    ov = read_type_overlay(slot).get(region, {})
    if isinstance(ov, dict) and scene in ov:
        return _type_entry(ov[scene])[1]
    return None


def scene_chars(slot, region, scene=None, scenes=None):
    """取某区域内可登场的预设角色（初始位置在该区域）。
    返回 [名称]。功能NPC 为身份标签、不落盘，不在此列。"""
    if not region or not scene:
        return []
    out = []
    pos = sm._load_npc_spawn()
    for name, loc in pos.items():
        if loc == region:
            out.append({"名称": name})
    return out



def merged_types(slot, region, scenes=None):
    """合并基线+覆盖层某区域的场景类型：返回 {场景:{类型,功能NPC}} dict（对象形态）。
    覆盖层覆盖基线同名场景。"""
    scenes = scenes if scenes is not None else load_scenes()
    out = OrderedDict()
    base = (scenes.get("场景类型", {}) or {}).get(region, {})
    if isinstance(base, dict):
        for scn, v in base.items():
            t, npc = _type_entry(v)
            if t:
                out[scn] = {"类型": t, "功能NPC": npc}
    if slot is not None:
        ov = read_type_overlay(slot).get(region, {})
        if isinstance(ov, dict):
            for scn, v in ov.items():
                t, npc = _type_entry(v)
                if t:
                    out[scn] = {"类型": t, "功能NPC": npc}
    return out


def scene_limit(region, scenes=None):
    """取某区域场景总量上限（含基线）；未在 scenes.json 上限表则兜底 _SCENE_DEFAULT_LIMIT。"""
    scenes = scenes if scenes is not None else load_scenes()
    return int(scenes.get("上限", {}).get(region, _SCENE_DEFAULT_LIMIT))


def merged_scenes(slot, region, scenes=None):
    """合并基线+覆盖层某区域的场景邻接：返回 {场景:{方位:邻场景}} dict。"""
    scenes = scenes if scenes is not None else load_scenes()
    merged = {}
    base = (scenes.get("场景", {}) or {}).get(region, {})
    if isinstance(base, dict):
        for scn, exits in base.items():
            merged[scn] = dict(exits) if isinstance(exits, dict) else {}
    overlay = read_overlay(slot).get(region, {})
    if isinstance(overlay, dict):
        for scn, exits in overlay.items():
            if not isinstance(exits, dict):
                continue
            merged.setdefault(scn, {})
            for d, nb in exits.items():
                merged[scn][d] = nb
    return merged


def parse_region_scene(pos, regions=None):
    """解析「区域·场景」→ (区域, 场景)。
    优先用已知区域名集合做最长前缀匹配（最稳，区域名即使内部含'·'也能正确切）；
    regions 缺省时回退为按首个'·'切（要求区域名内部不含'·'）。
    无'·'或无匹配 → (整串, None)。"""
    if not pos:
        return "", None
    if "·" not in pos:
        return pos, None
    if regions:
        # 已知区域名集合：取 pos 的最长前缀命中
        best = None
        for r in regions:
            if pos == r or pos.startswith(r + "·"):
                if best is None or len(r) > len(best):
                    best = r
        if best:
            rest = pos[len(best):]
            return best, (rest[1:] if rest.startswith("·") else (rest or None))
    # 回退：按首个'·'切（要求区域名内部不含'·'）
    region, _, detail = pos.partition("·")
    return region, (detail or None)


def _parse_pos(pos):
    """解析「区域·场景」→ (区域, 场景)；无「·」→ (区域, None)。
    区域名内部不得含'·'（如'洞庭湖（岳阳）'用全角括号，不用'·'）。"""
    if not pos or "·" not in pos:
        return pos or "", None
    region, _, detail = pos.partition("·")
    return region, (detail or None)


def _base_scenes(region, scenes=None):
    """取某区域的基线场景名集合。"""
    scenes = scenes if scenes is not None else load_scenes()
    base = (scenes.get("场景", {}) or {}).get(region, {})
    return set(base.keys()) if isinstance(base, dict) else set()


def _new_scene_count(slot, region, scenes=None):
    """覆盖层中真正新增的场景数（剔除本就在基线里的场景，避免反向边回写基线场景占配额）。"""
    overlay_region = read_overlay(slot).get(region, {})
    base = _base_scenes(region, scenes)
    if not isinstance(overlay_region, dict):
        return 0
    return sum(1 for scn in overlay_region if scn not in base)


def _disp_width(s):
    """显示宽度：全角字符（含中文、全角标点、【】、　、→、↓）按 2，半角按 1。"""
    w = 0
    for ch in s:
        w += 2 if ord(ch) > 0x2E7F or ch in "【】　→↓" else 1
    return w


def _render_adjacency_tree(merged, scene):
    """以当前场景为根，沿真实邻接方向延伸成树状多行字符串，UI 直接照搬即可。

    merged: 区域场景邻接 {场景:{方位:邻场景}}。scene: 当前场景名（用【】框起）。
    完整展开整个区域邻接（不截断深度），去环（已展开的场景不重复）；方位按 COMPASS_ORDER 排序。
    斜向同样算1跳。当前场景无邻接或孤点时仅输出根行。区域全部场景可达时覆盖全区域。"""
    if not scene:
        return ""
    # 方位排序索引
    order = {d: i for i, d in enumerate(COMPASS_ORDER)}

    def sorted_exits(scn):
        exits = (merged.get(scn) or {})
        return sorted(exits.items(), key=lambda kv: order.get(kv[0], 99))

    lines = [f"【{scene}】"]
    seen = {scene}

    def walk(scn, prefix, is_last):
        children = [(d, nb) for d, nb in sorted_exits(scn) if nb not in seen]
        for i, (d, nb) in enumerate(children):
            seen.add(nb)
            last = (i == len(children) - 1)
            connector = "└─" if last else "├─"
            lines.append(f"{prefix}{connector} {d}→ {nb}")
            walk(nb, prefix + ("   " if last else "│  "), last)

    walk(scene, "", True)
    return "\n".join(lines)


def build_map(slot, action, explore, resolve_region, station_type):
    """组装 map-ui 界面数据。

    action: 查看地图 action，可带 当前场景（GM 据 narration 提供的场景名）。
    explore: 当前 slot 的 explore dict（读写 explore.当前位置）。
    resolve_region(region, nodes): engine 提供的区域名→map.json 节点解析。
    station_type(region, nodes_info): engine 提供的取驿站类型。
    返回 {"界面":"map-ui", 当前区域, 当前场景, 驿站出口, 驿站类型, 邻接图, 已知地点:[...], 上限, 剩余配额}。
    """
    scenes = load_scenes()
    m = _load_map_for_station()
    nodes = m.get("节点", {})

    cur = explore.get("当前位置") or ""
    region, scene = _parse_pos(cur)
    region = resolve_region(region, nodes) or region
    # 当前位置无场景后缀 → 用 action.当前场景，并持久化为「区域·场景」
    if not scene:
        scene = action.get("当前场景")
        if scene and region:
            explore["当前位置"] = f"{region}·{scene}"

    # 区域无对应 map 节点 → 回退
    if not region or region not in nodes:
        return {"界面": "message-ui", "提示": f"当前位置【{cur}】无法解析区域，暂无地图"}

    merged = merged_scenes(slot, region, scenes)
    # 当前场景不在已登记场景中：仍展示，但不带出口（孤点）
    exits = merged.get(scene, {}) if scene else {}
    # 邻接图：以当前场景为根，沿真实邻接方向延伸成树（斜向同样算1跳），按深度截断、去环
    adj_tree = _render_adjacency_tree(merged, scene)

    # 已知地点清单：基线+覆盖层全部场景，标注 当前/功能类型（驿站出口不再单独加标，
    # 该场景类型即「驿站」，抬头已另示驿站出口）
    station_exit = (scenes.get("驿站出口", {}) or {}).get(region)
    region_types = merged_types(slot, region, scenes)
    known = []
    for scn in merged.keys():
        tags = []
        if scn == scene:
            tags.append("当前")
        entry = region_types.get(scn)
        if entry and entry.get("类型"):
            tags.append(entry["类型"])
        known.append({"名称": scn, "标记": tags or None})

    stype = station_type(region, nodes)
    limit = scene_limit(region, scenes)
    # 配额为该区域场景总量（基线∪覆盖层），已用 = 总数，剩余 = 上限 - 总数
    total = len(merged)
    remaining = max(0, limit - total)

    # 渲染模式：WUXIA_RPG_RENDER_MODULE=LLM（缺省）→ 文本邻接图；否则（WEB_UI）→ 结构化场景图。
    # 已知地点/驿站出口/驿站类型/当前区域/当前场景/配额 两种模式均带。
    llm_mode = os.environ.get("WUXIA_RPG_RENDER_MODULE", "LLM") == "LLM"
    payload = {"界面": "map-ui", "当前区域": region, "当前场景": scene,
               "驿站出口": station_exit, "驿站类型": stype,
               "已知地点": known, "上限": limit, "剩余配额": remaining}
    if llm_mode:
        payload["邻接图"] = adj_tree
    else:
        payload["场景图"] = merged
    return payload


def register_scene(slot, action, staged=None, type_staged=None):
    """登记场景（随剧情推动状态变更带入）。自动补反向边，达上限拒绝。

    为支持整轮事务回滚，本函数不直接落盘：把登记写入内存暂存 staged（dict，key=区域，
    value={场景:{方位:邻}}）；落盘由 commit_staged 完成。配额校验时把已暂存的同区域新增
    场景一并计入，避免一轮内连续登记越过上限。

    action: {区域, 场景, 方位出口: {方位: 邻场景}（可省略/为空，表示登记孤点）, 功能类型(可选:驿站/店铺/客栈), 功能NPC(可选:身份名,如驿丞/店主/掌柜)}
    staged: 本轮邻接暂存区（engine 传入，跨多条变更共享）；为 None 则即时落盘（非事务用法）。
    type_staged: 本轮场景类型暂存区（{区域:{场景:{类型,功能NPC}}}）；为 None 则类型即时落盘。
    返回 {"ok": bool, "msg", "变更"?, "剩余配额"?}。失败标记 _结算错误 由调用方处理。

    规则：未登记地点照常登记；已登记地点仅孤岛（无出口）可更新出入口；已登记非孤岛
    地点若传入出入口与现状不合则报错（如需重置请改用「隔离地点」）。类型可补不可改——
    已有类型且与传入不一致则报错。注：场景功能类型字段名为「功能类型」，避免与状态变更
    条目的「类型」字段（登记场景）冲突。
    """
    region = action.get("区域")
    scene = action.get("场景")
    exits = action.get("方位出口") or {}
    if not region or not scene:
        return {"ok": False, "msg": "登记场景须指定 区域、场景（方位出口可省略，登记为孤点）"}
    if not isinstance(exits, dict):
        return {"ok": False, "msg": "登记场景 方位出口 须为 {方位:邻场景} 字典"}

    stype = action.get("功能类型")
    if stype is not None and stype not in _SCENE_TYPES:
        return {"ok": False, "msg": f"非法场景类型【{stype}】，须取 驿站/店铺/客栈"}
    snpc = action.get("功能NPC")  # 功能NPC名（身份标签，非落盘角色）；仅功能类型场景有意义

    scenes = load_scenes()
    # 校验方位与目标合法
    for d, nb in exits.items():
        if d not in _SCENE_DIR_REVERSE:
            return {"ok": False, "msg": f"非法方位【{d}】，方位须取 北/东北/东/东南/南/西南/西/西北"}
        if nb == scene:
            return {"ok": False, "_结算错误": True,
                    "msg": f"地点【{scene}】的{d}方出口不能指向自身"}

    # 该场景是否已存在于基线 / 覆盖层 / 本轮暂存
    merged = merged_scenes(slot, region, scenes)
    staged_region = (staged or {}).get(region, {}) if staged else {}
    scene_exists = scene in merged or scene in staged_region
    # 当前现有出口（本轮暂存优先，覆盖 merged；重置孤点标记视为空出口）
    current_exits = dict(merged.get(scene, {}))
    if scene in staged_region:
        if staged_region[scene].get(_RESET_MARK):
            current_exits = {}
        else:
            current_exits.update(staged_region[scene])

    limit = scene_limit(region, scenes)
    # 配额为场景总量（含基线）：已用 = 基线∪覆盖层∪本轮暂存 场景总数
    combined = set(merged.keys()) | set(staged_region.keys())
    if not scene_exists and len(combined) >= limit:
        return {"ok": False,
                "msg": f"【{region}】已知场景已满（上限{limit}），不宜再添新景",
                "剩余配额": 0}

    if scene_exists:
        if current_exits:
            # 非孤岛：仅允许与现状完全一致的重复登记，出入口不合即报错
            same = (all(d in current_exits and current_exits[d] == nb for d, nb in exits.items())
                    and all(d in exits for d in current_exits))
            if not same:
                return {"ok": False, "_结算错误": True,
                        "msg": f"地点【{scene}】已登记且非孤岛，出入口与现状不合，不得直接更新；如需重置请先用「隔离地点」"}
            return {"ok": True, "msg": f"地点【{scene}】已登记且状态一致，无需重复登记",
                    "剩余配额": max(0, limit - len(combined))}
        # 孤岛：传入空则一致跳过；传入方位则补连接
        if not exits:
            return {"ok": True, "msg": f"地点【{scene}】已登记为孤点且状态一致，无需重复登记",
                    "剩余配额": max(0, limit - len(combined))}

    # 写入暂存区（或即时覆盖层）：新场景登记 或 孤岛补连接
    target = staged if staged is not None else read_overlay(slot)
    target.setdefault(region, {})

    # 取某场景在「基线∪覆盖层∪本轮暂存」下的现有出口（重置孤点标记视为空）。
    # 与上方 current_exits 同口径，供反向边冲突检查复用。
    def _exits_of(name):
        out = dict(merged.get(name, {}))
        staged_name = staged_region.get(name, {})
        if staged_name.get(_RESET_MARK):
            return {}
        if name in staged_region:
            out.update(staged_name)
        return out

    new_exits = {d: nb for d, nb in exits.items()}
    # 反向边冲突检查：A→[d]→B 要求 B 的 rev 方向只能是 A（或为空），
    # 否则覆盖既有路径，须报错回滚，由 GM 改用其他方位或先隔离 B。
    for d, nb in new_exits.items():
        rev = _SCENE_DIR_REVERSE[d]
        nb_exits = _exits_of(nb)
        existing = nb_exits.get(rev)
        if existing and existing != scene:
            return {"ok": False, "_结算错误": True,
                    "msg": f"地点【{nb}】的{rev}方已连通【{existing}】，"
                           f"无法再接【{scene}】（请重新设计路径）"}

    prev = target[region].get(scene, {})
    base_exits = {} if prev.get(_RESET_MARK) else dict(prev)
    base_exits.update(new_exits)
    target[region][scene] = base_exits
    # 反向边（经冲突检查，安全写入）
    for d, nb in new_exits.items():
        target[region].setdefault(nb, {})
        target[region][nb][_SCENE_DIR_REVERSE[d]] = scene

    if staged is None:
        write_overlay(slot, target)

    # 场景类型：可补不可改（已有类型且与传入不一致则报错回滚）
    if stype is not None:
        existing_type = scene_type(slot, region, scene, scenes)
        existing_npc = scene_npc(slot, region, scene, scenes)
        # 本轮暂存里已写的类型优先
        if type_staged is not None and region in type_staged and scene in type_staged[region]:
            t, npc = _type_entry(type_staged[region][scene])
            existing_type, existing_npc = t, npc
        if existing_type is not None and existing_type != stype:
            return {"ok": False, "_结算错误": True,
                    "msg": f"地点【{scene}】已有类型【{existing_type}】，不得改为【{stype}】；如需改类型请先「隔离地点」再重登"}
        if existing_type != stype or (snpc and existing_npc != snpc):
            entry = {"类型": stype, "功能NPC": snpc or existing_npc}
            if type_staged is not None:
                type_staged.setdefault(region, {})[scene] = entry
            else:
                tov = read_type_overlay(slot)
                tov.setdefault(region, {})[scene] = entry
                write_type_overlay(slot, tov)
            # 类型/功能NPC 落盘完成（type_change 不再拼入对玩家的 变更 文案）

    used = len(combined) + (0 if scene_exists else 1)
    # 变更文案（类型/功能NPC为内部机制，不暴露给玩家，故不带 type_change）
    if exits:
        change = (f"地点【{scene}】已连通" if scene_exists
                  else f"地点【{scene}】已登记，路径已解锁")
    else:
        change = f"地点【{scene}】已登记，路径不明"
    return {"ok": True, "msg": f"已登记【{region}·{scene}】入地图",
            "变更": change,
            "剩余配额": max(0, limit - used)}


def isolate_scene(slot, action, staged=None):
    """隔离地点（状态变更「隔离地点」带入）：将已登记地点重置为孤岛（清空现有方位出口
    及反向边，剧情需暂时不可达时用）。不直接落盘：写入内存暂存 staged 标记 _RESET_MARK，
    commit_staged 落盘以支持整轮回滚。

    action: {区域, 场景}（须为已登记地点）
    staged: 本轮暂存区（engine 传入，跨多条变更共享）；为 None 则即时落盘（非事务用法）。
    返回 {"ok": bool, "msg", "变更"?}。失败标记 _结算错误 由调用方处理。
    """
    region = action.get("区域")
    scene = action.get("场景")
    if not region or not scene:
        return {"ok": False, "msg": "隔离地点须指定 区域、场景"}

    merged = merged_scenes(slot, region)
    staged_region = (staged or {}).get(region, {}) if staged else {}
    if scene not in merged and scene not in staged_region:
        return {"ok": False, "_结算错误": True, "msg": f"地点【{scene}】未登记，无需隔离"}

    current_exits = dict(merged.get(scene, {}))
    if scene in staged_region:
        if staged_region[scene].get(_RESET_MARK):
            current_exits = {}
        else:
            current_exits.update(staged_region[scene])
    if not current_exits:
        return {"ok": True, "msg": f"地点【{scene}】已为孤岛，无需重复隔离"}

    target = staged if staged is not None else read_overlay(slot)
    target.setdefault(region, {})
    if staged is not None:
        # 标记重置：commit 时清 overlay 现有出口及反向边
        target[region][scene] = {_RESET_MARK: True}
    else:
        # 非事务：即时清 overlay 现有出口及反向边
        target[region][scene] = {}
        for d, nb in current_exits.items():
            rd = _SCENE_DIR_REVERSE[d]
            if nb in target[region] and target[region][nb].get(rd) == scene:
                target[region][nb].pop(rd, None)
        write_overlay(slot, target)
    return {"ok": True, "msg": f"地点【{scene}】已隔离为孤岛（暂时不可达）",
            "变更": f"地点【{scene}】已隔离为孤岛"}


# 重置孤点标记键：staged 中某场景 exits 含此键表示清空为孤点（commit 时清掉 overlay 现有出口）
_RESET_MARK = "__重置孤点__"


def commit_staged(slot, staged, type_staged=None):
    """把本轮暂存的场景登记合并落盘到 map_overlay.json（+ scene_types_overlay.json）。
    整轮全部通过后由 engine 调用。

    方位级增量合并（同一场景多方位分次登记）；含重置孤点标记时清空该场景 overlay 现有出口。
    type_staged 非空时一并把场景类型合并落盘到 scene_types_overlay.json。"""
    if staged:
        overlay = read_overlay(slot)
        for region, region_scenes in staged.items():
            overlay.setdefault(region, {})
            for scn, exits in region_scenes.items():
                if exits.get(_RESET_MARK):
                    # 重置为孤点：清空 overlay 现有出口及反向边
                    old = dict(overlay[region].get(scn, {}))
                    overlay[region][scn] = {}
                    for d, nb in old.items():
                        rd = _SCENE_DIR_REVERSE[d]
                        if nb in overlay[region] and overlay[region][nb].get(rd) == scn:
                            overlay[region][nb].pop(rd, None)
                    continue
                overlay[region].setdefault(scn, {})
                overlay[region][scn].update(exits)
        write_overlay(slot, overlay)
    if type_staged:
        tov = read_type_overlay(slot)
        for region, region_types in type_staged.items():
            tov.setdefault(region, {})
            tov[region].update(region_types)
        write_type_overlay(slot, tov)


def _load_map_for_station():
    """严格读取 map.json，供 build_map 解析区域与驿站类型。"""
    path = os.path.join(HERE, "..", "assets", "data", "map.json")
    return read_json(path, expected_type=dict)
