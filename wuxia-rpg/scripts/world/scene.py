#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""区域内场景图模块：基线 scenes.json + per-slot 覆盖层 map_overlay.json。

数据组织（assets/data/scenes.json，边表格式）：
- 上限：{区域: 该区域场景总量上限}（含基线场景）。未列区域兜底 _SCENE_DEFAULT_LIMIT。
- 驿站出口：{区域: 出城所经驿站场景名}。
- 场景：{区域: {"场景": [场景名...], "边": [["场景名.方位", "场景名.方位"], ...]}}。
  每条边双方位内联且互为反向；每场景每方位至多一个邻接点；
  在场景列表但不出现在任何边中者为孤点。格式细节与解析见 world/scene_format.py。

覆盖层（save/slot_{N}/map_overlay.json）：GM 运行时新增的场景，随存档 save/restore 同步。
结构同基线「场景」一层，另可带 "删边"（从 基线∪覆盖层 边并集中扣除，隔离/重连用）。
旧格式覆盖层（每场景 {方位:邻} dict）读入即自动迁移。渲染取 基线 ∪ 覆盖层。

暴露给 engine：
- build_map(slot, action, explore, resolve_region, station_type) → map-ui 数据
  （邻接图 + 已知地点清单 + 驿站出口）
- register_scene(slot, action, staged) → 预校验并暂存地点登记（由 scene-prepare 草稿在 judge 内采用，
  组边为双方位内联，达上限拒绝；commit_staged 仅在整轮成功后落盘）
- commit_staged(slot, staged) → 整轮通过后把暂存登记合并落盘
- merged_scenes(slot, region) → {场景:{方位:邻场景}} 视图（两侧方位都填，供寻路/展示/校验）
- overlay 同步钩子（save/restore 用）：read_overlay / write_overlay
"""
import difflib
import os
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from common.json_io import read_json
from common.render_mode import render_mode
from store import save_manager as sm
from world import scene_format as sf

_SCENES_PATH = os.path.join(HERE, "..", "assets", "data", "scenes.json")
_SCENE_DEFAULT_LIMIT = 16  # 未在 scenes.json 上限表中的区域兜底上限
# 场景邻接方位及反向映射（合法方位集 = 其键集）
_SCENE_DIR_REVERSE = sf.DIR_REVERSE
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
    """读取 slot 覆盖层并归一为边表格式；缺失/损坏返回 {}。
    旧格式（每场景 {方位:邻} dict，含 "__完整替换__" 标记）读入即迁移，
    存量存档文件不动；仅当确有旧条目时才载入基线计算替换标记。"""
    raw = sm.read_map_overlay(slot)
    if not isinstance(raw, dict) or not raw:
        return {}
    if any(isinstance(v, dict) and sf.is_legacy_region(v) for v in raw.values()):
        return sf.normalize_overlay(raw, baseline=load_scenes())
    return raw


def write_overlay(slot, data):
    """写 slot 覆盖层（边表格式）；data 为空时删除文件以保持整洁。
    输出净化：移边为暂存期专用不落盘；空 删边/场景 列表不落盘。"""
    if isinstance(data, dict) and data:
        clean = {}
        for region, entry in data.items():
            if not isinstance(entry, dict):
                continue
            out = {"场景": list(entry.get("场景") or []),
                   "边": [e for e in (entry.get("边") or []) if sf.canonical_edge(e)]}
            removed = [e for e in (entry.get(sf.REMOVE_KEY) or []) if sf.canonical_edge(e)]
            if removed:
                out[sf.REMOVE_KEY] = removed
            clean[region] = out
        data = clean
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


def scene_type(slot, region, scene, scenes=None, staged=None):
    """取某场景的功能类型（基线∪覆盖层∪本轮暂存）。"""
    if not region or not scene:
        return None
    if staged and scene in (staged.get(region, {}) or {}):
        return _type_entry(staged[region][scene])[0]
    scenes = scenes if scenes is not None else load_scenes()
    base_types = (scenes.get("场景类型", {}) or {}).get(region, {})
    if isinstance(base_types, dict) and scene in base_types:
        return _type_entry(base_types[scene])[0]
    ov = read_type_overlay(slot).get(region, {})
    if isinstance(ov, dict) and scene in ov:
        return _type_entry(ov[scene])[0]
    return None


def scene_npc(slot, region, scene, scenes=None, staged=None):
    """取某场景的功能NPC名（基线∪覆盖层∪本轮暂存）。"""
    if not region or not scene:
        return None
    if staged and scene in (staged.get(region, {}) or {}):
        return _type_entry(staged[region][scene])[1]
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


def known_regions(scenes=None):
    """全部已知区域名（基线 上限表 ∪ 场景表）。登记/隔离的区域必须取自其中。"""
    scenes = scenes if scenes is not None else load_scenes()
    return set(scenes.get("上限", {}) or {}) | set(scenes.get("场景", {}) or {})


def _unknown_region_error(region, known):
    """未知区域报错文案；difflib 就近匹配帮助 GM 纠正区域名。"""
    match = difflib.get_close_matches(region, known, n=1, cutoff=0.4)
    hint = f"（是否指【{match[0]}】？）" if match else ""
    return f"未知区域【{region}】{hint}：区域名须取自基线地图，不得自创区域"


def _baseline_region(scenes, region):
    """基线某区域 → (场景名列表, 边列表)；区域缺失返回空。"""
    data = (scenes.get("场景", {}) or {}).get(region)
    if not isinstance(data, dict):
        return [], []
    if sf.is_legacy_region(data):
        names, edges, _ = sf.normalize_region(data)
        return names, [sf.canonical_edge(e) for e in edges]
    out = []
    for edge in data.get("边") or []:
        canon = sf.canonical_edge(edge)
        if canon:
            out.append(canon)
    return list(data.get("场景") or []), out


def merged_scenes(slot, region, scenes=None):
    """合并基线+覆盖层某区域的场景邻接：返回 {场景:{方位:邻场景}} 视图。
    有效边 = (基线边 ∪ 覆盖层边) − 删边；两侧方位都填，孤点为空 dict。"""
    scenes = scenes if scenes is not None else load_scenes()
    base_names, base_edges = _baseline_region(scenes, region)
    ov = read_overlay(slot).get(region) or {} if slot is not None else {}
    ov_names = ov.get("场景") or []
    ov_edges = [e for e in (ov.get("边") or []) if sf.canonical_edge(e)]
    edges = sf.effective_edges(base_edges, ov_edges, ov.get(sf.REMOVE_KEY) or [])
    names = list(base_names) + [n for n in ov_names if n not in set(base_names)]
    return sf.region_view(names, edges)


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
    return set(_baseline_region(scenes, region)[0])


def _staged_region(staged, region):
    """本轮暂存区某区域条目 → {"场景", "边", "删边", "移边"}（缺省空）。
    移边为暂存期专用：覆盖层边的物理删除，commit 时应用，不持久化。"""
    entry = (staged or {}).get(region)
    if not isinstance(entry, dict):
        return {"场景": [], "边": [], "删边": [], "移边": []}
    return {"场景": list(entry.get("场景") or []),
            "边": [e for e in (entry.get("边") or []) if sf.canonical_edge(e)],
            "删边": [e for e in (entry.get(sf.REMOVE_KEY) or []) if sf.canonical_edge(e)],
            "移边": [e for e in (entry.get("移边") or []) if sf.canonical_edge(e)]}


def _active_edges(staged_entry, overlay_edges):
    """暂存生效的覆盖层边 = (覆盖层边 ∪ 暂存边) − 暂存移边（按规范形态）。"""
    out, seen = [], set()
    for edge in list(overlay_edges or []) + list(staged_entry.get("边") or []):
        canon = sf.canonical_edge(edge)
        if not canon or tuple(canon) in seen:
            continue
        out.append(canon)
        seen.add(tuple(canon))
    removed = {tuple(e) for e in staged_entry.get("移边") or []}
    return [e for e in out if tuple(e) not in removed]


def _effective_view(slot, region, scenes, staged_entry):
    """基线∪覆盖层∪本轮暂存 的有效场景视图（含暂存删边/移边/新增边）。
    返回 (视图, 磁盘覆盖层边, 生效覆盖层边)；后两者供隔离作边来源判定。"""
    base_names, base_edges = _baseline_region(scenes, region)
    ov = read_overlay(slot).get(region) or {}
    ov_edges = [e for e in (ov.get("边") or []) if sf.canonical_edge(e)]
    ov_names = ov.get("场景") or []
    removed = {tuple(sf.canonical_edge(x)) for x in (ov.get(sf.REMOVE_KEY) or [])}
    removed |= {tuple(e) for e in staged_entry["删边"]}
    eff_base = [e for e in base_edges if tuple(e) not in removed]
    active = _active_edges(staged_entry, ov_edges)
    names = list(base_names) + [n for n in list(ov_names) + staged_entry["场景"]
                                if n not in set(base_names)]
    view = sf.region_view(names, sf.effective_edges(eff_base, active, []))
    return view, ov_edges, active


def _region_entry(container, region):
    """取（或建）边表格式的区域条目；staged/overlay 共用。"""
    entry = container.get(region)
    if not isinstance(entry, dict) or "边" not in entry:
        entry = {"场景": list((entry or {}).get("场景") or []) if isinstance(entry, dict) else [],
                 "边": []}
        container[region] = entry
    entry.setdefault(sf.REMOVE_KEY, [])
    return entry


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

    # 渲染模式（经 common.render_mode 归一，未设置=LLM）：
    # LLM → 文本邻接图（Markdown 用）；
    # 其余（WEB_UI/dsh 等）→ 场景图+邻接图并存（卡片消费结构化，渲染文本用邻接图）。
    # 已知地点/驿站出口/驿站类型/当前区域/当前场景/配额 各模式均带。
    mode = render_mode()
    payload = {"界面": "map-ui", "当前区域": region, "当前场景": scene,
               "驿站出口": station_exit, "驿站类型": stype,
               "已知地点": known, "上限": limit, "剩余配额": remaining}
    if mode == "LLM":
        payload["邻接图"] = adj_tree
    else:
        payload["场景图"] = merged
        payload["邻接图"] = adj_tree
    return payload


def register_scene(slot, action, staged=None, type_staged=None, known_targets=None):
    """预校验并暂存场景登记（边表）。组边为双方位内联，达上限拒绝。

    为支持整轮事务回滚，本函数不直接落盘：把登记写入内存暂存 staged（{区域:
    {"场景": [...], "边": [...], "删边": [...]}}）；落盘由 commit_staged 完成。
    配额校验时把已暂存的同区域新增场景一并计入，避免一轮内连续登记越过上限。

    action: {区域, 场景, 方位出口: {方位: 邻场景}（可省略/为空，表示登记孤点）, 功能类型(可选:驿站/店铺/客栈), 功能NPC(可选:身份名,如驿丞/店主/掌柜)}
    staged: 本轮邻接暂存区（engine 传入，跨多条变更共享）；为 None 则即时落盘（非事务用法）。
    type_staged: 本轮场景类型暂存区（{区域:{场景:{类型,功能NPC}}}）；为 None 则类型即时落盘。
    known_targets: 同批次登记的场景名集合（本区域），供出口目标前向引用——批次内 A↔B 任意书写顺序均可。
    返回 {"ok": bool, "msg", "变更"?, "剩余配额"?}。失败标记 _结算错误 由调用方处理。

    规则：未登记地点照常登记；已登记地点仅孤岛（无出口）可更新出入口；已登记非孤岛
    地点若传入出入口与现状不合则报错（如需重置请改用「隔离地点」）。类型可补不可改——
    已有类型且与传入不一致则报错。区域须为基线已知区域；出口目标须为已登记地点
    （基线∪覆盖层∪本轮暂存∪同批次），防止隐式创建幽灵场景或平移其他区域同名地点。
    方位槽唯一：A→[d]→B 要求 B 的 rev 方位只能是 A（或为空）。
    场景名不得包含「.」（边标签以 场景名.方位 解析）。
    注：场景功能类型字段名为「功能类型」，避免与状态变更条目的「类型」字段（登记场景）冲突。
    """
    region = action.get("区域")
    scene = action.get("场景")
    exits = action.get("方位出口") or {}
    if not region or not scene:
        return {"ok": False, "msg": "登记场景须指定 区域、场景（方位出口可省略，登记为孤点）"}
    if not isinstance(exits, dict):
        return {"ok": False, "msg": "登记场景 方位出口 须为 {方位:邻场景} 字典"}
    if "." in scene:
        return {"ok": False, "msg": "场景名不得包含「.」（边标签以 场景名.方位 解析）"}

    stype = action.get("功能类型")
    if stype is not None and stype not in _SCENE_TYPES:
        return {"ok": False, "msg": f"非法场景类型【{stype}】，须取 驿站/店铺/客栈"}
    snpc = action.get("功能NPC")  # 功能NPC名（身份标签，非落盘角色）；仅功能类型场景有意义

    scenes = load_scenes()
    known = known_regions(scenes)
    if region not in known:
        return {"ok": False, "_结算错误": True, "msg": _unknown_region_error(region, known)}
    # 校验方位与目标合法
    for d, nb in exits.items():
        if d not in _SCENE_DIR_REVERSE:
            return {"ok": False, "msg": f"非法方位【{d}】，方位须取 北/东北/东/东南/南/西南/西/西北"}
        if not isinstance(nb, str) or "." in nb:
            return {"ok": False, "msg": "出口目标须为场景名且不得包含「.」"}
        if nb == scene:
            return {"ok": False, "_结算错误": True,
                    "msg": f"地点【{scene}】的{d}方出口不能指向自身"}

    # 该场景是否已存在于基线 / 覆盖层 / 本轮暂存（有效视图含暂存删边/移边/新增）
    staged_entry = _staged_region(staged, region)
    view, _, _ = _effective_view(slot, region, scenes, staged_entry)

    # 出口目标存在性：只能指向已登记地点（基线∪覆盖层∪本轮暂存∪同批次），
    # 未登记目标会被隐式登记成幽灵场景，甚至把其他区域的同名地点平移进来
    for d, nb in exits.items():
        if nb not in view and nb not in (known_targets or set()):
            return {"ok": False, "_结算错误": True,
                    "msg": f"出口目标【{nb}】未登记：方位出口须指向已登记地点；"
                           f"新地点请先在同批次登记（或先登记为孤点）再建立连接"}
    scene_exists = scene in view
    current_exits = view.get(scene, {})

    limit = scene_limit(region, scenes)
    # 配额为场景总量（含基线）：已用 = 基线∪覆盖层∪本轮暂存 场景总数
    combined = set(view.keys())
    if not scene_exists and len(combined) >= limit:
        return {"ok": False,
                "msg": f"【{region}】已知场景已满（上限{limit}），不宜再添新景",
                "剩余配额": 0}

    # 场景名先幂等入列：同批前向引用的镜像一致登记走"状态一致"早退，也不丢名
    # （边表模型里名字不随边隐式登记，与旧模型的镜像回写不同）
    target = staged if staged is not None else read_overlay(slot)
    entry = _region_entry(target, region)
    if scene not in entry["场景"]:
        entry["场景"].append(scene)

    if scene_exists:
        if current_exits:
            # 非孤岛：仅允许与现状完全一致的重复登记，出入口不合即报错
            if current_exits != dict(exits):
                return {"ok": False, "_结算错误": True,
                        "msg": f"地点【{scene}】已登记且非孤岛，出入口与现状不合，不得直接更新；如需重置请先用「隔离地点」"}
            return {"ok": True, "msg": f"地点【{scene}】已登记且状态一致，无需重复登记",
                    "剩余配额": max(0, limit - len(combined))}
        # 孤岛：传入空则一致跳过；传入方位则补连接
        if not exits:
            return {"ok": True, "msg": f"地点【{scene}】已登记为孤点且状态一致，无需重复登记",
                    "剩余配额": max(0, limit - len(combined))}

    # 方位槽冲突检查：A→[d]→B 要求 B 的 rev 方位只能是 A（或为空），
    # 否则覆盖既有路径，须报错回滚，由 GM 改用其他方位或先隔离 B。
    for d, nb in exits.items():
        rev = _SCENE_DIR_REVERSE[d]
        existing = view.get(nb, {}).get(rev)
        if existing and existing != scene:
            return {"ok": False, "_结算错误": True,
                    "msg": f"地点【{nb}】的{rev}方已连通【{existing}】，"
                           f"无法再接【{scene}】（请重新设计路径）"}

    # 写入暂存区（或即时覆盖层）：组边（双方位内联，天然自洽）。
    # 重连复活：同批先隔离再重登同一条边时，先撤回暂存移边，避免登记边被扣。
    seen = {tuple(sf.canonical_edge(e)) for e in entry["边"]}
    for d, nb in exits.items():
        edge = sf.canonical_edge([f"{scene}.{d}", f"{nb}.{_SCENE_DIR_REVERSE[d]}"])
        if not edge:
            continue
        entry["移边"] = [e for e in entry.get("移边") or [] if list(e) != edge]
        if tuple(edge) not in seen:
            entry["边"].append(edge)
            seen.add(tuple(edge))

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
                    "msg": f"地点【{scene}】已有类型【{existing_type}】，不得改为【{stype}】"}
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
    """将已登记地点的全部触及边删除，置为孤点（节点保留，仍占配额）；暂存以支持整轮回滚。
    触及边按来源分流：覆盖层边（磁盘∪本轮暂存）记入暂存移边（commit 物理移除），
    基线边记入删边（只扣基线，重连时可经覆盖层复活）。"""
    region = action.get("区域")
    scene = action.get("场景")
    if not region or not scene:
        return {"ok": False, "msg": "隔离地点须指定 区域、场景"}

    scenes = load_scenes()
    known = known_regions(scenes)
    if region not in known:
        return {"ok": False, "_结算错误": True, "msg": _unknown_region_error(region, known)}
    merged = merged_scenes(slot, region, scenes)
    staged_entry = _staged_region(staged, region)
    view, ov_edges, active_edges = _effective_view(slot, region, scenes, staged_entry)
    if scene not in view:
        return {"ok": False, "_结算错误": True, "msg": f"地点【{scene}】未登记，无需隔离"}

    current_exits = view.get(scene, {})
    if not current_exits:
        return {"ok": True, "msg": f"地点【{scene}】已为孤岛，无需重复隔离"}

    # 触及边：按两端当前方位标签重建；来源=覆盖层（磁盘∪暂存）或基线
    overlay_origin = {tuple(e) for e in list(ov_edges) + staged_entry["边"]}
    touching = []
    for d, nb in current_exits.items():
        reverse = None
        for nd, target in (view.get(nb) or {}).items():
            if target == scene:
                reverse = nd
                break
        other = f"{nb}.{reverse}" if reverse else f"{nb}.{_SCENE_DIR_REVERSE[d]}"
        canon = sf.canonical_edge([f"{scene}.{d}", other])
        if canon:
            touching.append(canon)

    target = staged if staged is not None else read_overlay(slot)
    entry = _region_entry(target, region)
    seen_del = {tuple(sf.canonical_edge(e)) for e in entry[sf.REMOVE_KEY]}
    seen_move = {tuple(sf.canonical_edge(e)) for e in entry.get("移边") or []}
    for canon in touching:
        if tuple(canon) in overlay_origin:
            # 覆盖层边：即时模式物理移除；事务模式记入移边（commit 应用，重连可复活）
            if staged is None:
                entry["边"] = [e for e in entry["边"] if sf.canonical_edge(e) != canon]
            elif tuple(canon) not in seen_move:
                entry.setdefault("移边", []).append(canon)
                seen_move.add(tuple(canon))
        elif tuple(canon) not in seen_del:
            entry[sf.REMOVE_KEY].append(canon)
            seen_del.add(tuple(canon))

    if staged is None:
        write_overlay(slot, target)
    return {"ok": True, "msg": f"地点【{scene}】已隔离为孤岛（暂时不可达）",
            "变更": f"地点【{scene}】已隔离为孤岛"}


def commit_staged(slot, staged, type_staged=None):
    """把本轮场景暂存合并落盘：场景名并集；边 =(磁盘边∪暂存边)−暂存移边（物理应用）；
    删边并集（只扣基线的持久标记；移边不落盘）。"""
    if staged:
        overlay = read_overlay(slot)
        for region, staged_entry in staged.items():
            if not isinstance(staged_entry, dict):
                continue
            target = _region_entry(overlay, region)
            base_names = set(target["场景"])
            for name in staged_entry.get("场景") or []:
                if name not in base_names:
                    target["场景"].append(name)
                    base_names.add(name)
            seen = {tuple(sf.canonical_edge(e)) for e in target["边"]}
            merged_edges = list(target["边"])
            for edge in staged_entry.get("边") or []:
                canon = sf.canonical_edge(edge)
                if canon and tuple(canon) not in seen:
                    merged_edges.append(canon)
                    seen.add(tuple(canon))
            moved = {tuple(e) for e in staged_entry.get("移边") or []}
            target["边"] = [e for e in merged_edges
                            if tuple(sf.canonical_edge(e)) not in moved]
            seen_del = {tuple(sf.canonical_edge(e)) for e in target[sf.REMOVE_KEY]}
            for edge in staged_entry.get(sf.REMOVE_KEY) or []:
                canon = sf.canonical_edge(edge)
                if canon and tuple(canon) not in seen_del:
                    target[sf.REMOVE_KEY].append(canon)
                    seen_del.add(tuple(canon))
            if not target[sf.REMOVE_KEY]:
                target.pop(sf.REMOVE_KEY)  # 空删边不落盘，保持覆盖层精简
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
