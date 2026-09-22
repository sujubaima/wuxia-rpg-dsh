#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景图边表格式层：标签解析、视图重建与旧格式迁移。无项目内依赖，供
world/scene.py（权威读写者）与 store/save_manager.py（存档恢复）共用。

新格式（基线 scenes.json 与覆盖层 map_overlay.json 同构）：
    {区域: {"场景": [场景名...], "边": [["场景名.方位", "场景名.方位"], ...],
            "删边": [...]（仅覆盖层；只从基线边中扣除，覆盖层边不受影响）}}
隔离产生的覆盖层边删除走暂存期 "移边"（commit 时物理移除，可被同批重新登记复活），
不落盘为持久标记。
- 每条边双方位内联且互为反向；每场景每方位至多一个邻接点；
- 孤点 = 在场景列表但不出现在任何边中。

旧格式（仅存量数据，读入即迁移，不回写）：
    {区域: {场景: {方位: 邻场景}}}
含 "__完整替换__" 标记的条目表示该场景出口全量替换（隔离/重连的旧机制），
迁移时转为：删该场景的全部基线触及边 + 声明出口成新边。
"""

# 方位反向映射；键集合即合法方位集
DIR_REVERSE = {"北": "南", "南": "北", "东": "西", "西": "东",
               "东北": "西南", "西南": "东北", "东南": "西北", "西北": "东南"}
REMOVE_KEY = "删边"  # 覆盖层专有：从基线∪覆盖层边并集中扣除的边
_REPLACE_MARK = "__完整替换__"  # 旧格式内部标记


def parse_label(label):
    """解析 "场景名.方位" → (场景, 方位)；非法返回 None。"""
    if not isinstance(label, str) or label.count(".") != 1:
        return None
    name, direction = label.rsplit(".", 1)
    if not name or direction not in DIR_REVERSE:
        return None
    return name, direction


def canonical_edge(edge):
    """边 → 规范形态 [label_lo, label_hi]（按标签排序）；非法返回 None。"""
    if not isinstance(edge, (list, tuple)) or len(edge) != 2:
        return None
    a, b = edge
    if not isinstance(a, str) or not isinstance(b, str):
        return None
    return [a, b] if a <= b else [b, a]


def region_view(names, edges):
    """边表 → {场景:{方位:邻场景}} 视图（两侧方位都填；非法边静默跳过）。"""
    view = {name: {} for name in names or []}
    for edge in edges or []:
        canon = canonical_edge(edge)
        if not canon:
            continue
        parsed_a = parse_label(canon[0])
        parsed_b = parse_label(canon[1])
        if not parsed_a or not parsed_b or parsed_a[0] == parsed_b[0]:
            continue
        (na, da), (nb, db) = parsed_a, parsed_b
        view.setdefault(na, {})[da] = nb
        view.setdefault(nb, {})[db] = na
    return view


def effective_edges(baseline_edges, overlay_edges, removed_edges):
    """有效边 = (基线边 − 删边) ∪ 覆盖层边（按规范形态比对）。
    删边只扣基线：覆盖层重新声明的同名边（隔离后重连、替换后保留）得以存活。"""
    removed = {tuple(c) for c in (canonical_edge(e) for e in removed_edges or []) if c}
    out = []
    seen = set()
    for edge in baseline_edges or []:
        canon = canonical_edge(edge)
        if not canon or tuple(canon) in seen:
            continue
        if tuple(canon) not in removed:
            out.append(canon)
            seen.add(tuple(canon))
    for edge in overlay_edges or []:
        canon = canonical_edge(edge)
        if not canon or tuple(canon) in seen:
            continue
        out.append(canon)
        seen.add(tuple(canon))
    return out


def _legacy_dict_edges(declared):
    """旧格式声明 {场景:{方位:邻}} → 边列表（成对合并，单向边物化反向）。"""
    edges = {}
    first = {}
    for scene, exits in declared.items():
        for direction, neighbor in (exits or {}).items():
            if direction not in DIR_REVERSE or neighbor == scene:
                continue
            pair = tuple(sorted((scene, neighbor)))
            if pair in edges:
                continue
            if pair in first:
                n0, d0 = first[pair]
                if n0 == scene:
                    continue  # 同场景对方位重复声明，取首个
                edges[pair] = [f"{n0}.{d0}", f"{scene}.{direction}"]
            else:
                first[pair] = (scene, direction)
    for pair, (n0, d0) in first.items():
        if pair not in edges:
            other = pair[1] if pair[0] == n0 else pair[0]
            edges[pair] = [f"{n0}.{d0}", f"{other}.{DIR_REVERSE[d0]}"]
    return list(edges.values())


def is_legacy_region(value):
    """识别旧格式区域值：{场景:{方位:邻}}（新格式含 场景/边 列表键）。"""
    if not isinstance(value, dict) or "边" in value or "场景" in value:
        return False
    return all(isinstance(v, dict) for v in value.values()) if value else True


def normalize_region(value, baseline_edges=None, baseline_names=None):
    """区域值 → 新格式 (场景列表, 边列表, 删边列表)。新格式原样透传；
    旧格式按声明组成边，"__完整替换__" 条目转为删基线触及边 + 声明边。"""
    if not isinstance(value, dict):
        return [], [], []
    if not is_legacy_region(value):
        names = list(value.get("场景") or [])
        edges = [e for e in (value.get("边") or []) if canonical_edge(e)]
        removed = [e for e in (value.get(REMOVE_KEY) or []) if canonical_edge(e)]
        return names, edges, removed

    # 旧格式迁移
    declared = {}
    replaced = set()
    for scene, exits in value.items():
        if not isinstance(exits, dict):
            continue
        if exits.get(_REPLACE_MARK):
            replaced.add(scene)
        declared[scene] = {d: nb for d, nb in exits.items()
                            if d in DIR_REVERSE and isinstance(nb, str)}
    names = list(value.keys())
    edges = _legacy_dict_edges(declared)
    removed = []
    for scene in replaced:
        for edge in baseline_edges or []:
            parsed = [parse_label(str(x)) for x in edge]
            if any(p and p[0] == scene for p in parsed):
                removed.append(canonical_edge(edge))
    return names, edges, removed


def normalize_overlay(overlay, baseline=None):
    """整份覆盖层 → 新格式；旧格式（含替换标记）读入即迁移。
    baseline 为基线 scenes dict（load_scenes() 结果），迁移替换标记时
    用于计算基线触及边；缺省时含替换标记的旧条目按无基线边处理。"""
    if not isinstance(overlay, dict):
        return {}
    out = {}
    for region, value in overlay.items():
        if isinstance(value, dict) and not is_legacy_region(value):
            out[region] = value
            continue
        base_region = ((baseline or {}).get("场景", {}) or {}).get(region)
        base_edges = list(base_region.get("边") or []) if isinstance(base_region, dict) else []
        names, edges, removed = normalize_region(value, baseline_edges=base_edges)
        entry = {"场景": names, "边": edges}
        if removed:
            entry[REMOVE_KEY] = removed
        out[region] = entry
    return out
