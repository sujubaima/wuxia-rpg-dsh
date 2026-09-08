#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GM 侧场景图查询工具（命令行，不走 engine go）。

查某区域已登记的全部场景（基线∪存档覆盖层）、各场景方位出口、配额余量、孤点（无出口待补）。
正式存档带 --slot N 读该 slot 的覆盖层；不带 --slot 则只看基线。

用法：
  python3 scripts/map_query.py <区域> [--slot N]   # 查某区域场景图
  python3 scripts/map_query.py 配额               # 列全区域配额表
  python3 scripts/map_query.py -h

区域名支持子串模糊匹配（如 "洛阳" 匹配 "洛阳"）。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from world import scene as sc


def _resolve_region(name, scenes):
    """区域名模糊匹配：精确 → 子串。返回节点名或 None。"""
    regions = list((scenes.get("上限", {}) or {}).keys())
    if name in regions:
        return name
    hits = [r for r in regions if name in r]
    if len(hits) == 1:
        return hits[0]
    return None


def query_region(region_name, slot=None):
    """返回区域场景图的结构化结果；未找到或匹配歧义时返回 ``错误``。"""
    scenes = sc.load_scenes()
    region = _resolve_region(region_name, scenes)
    if region is None:
        return {"错误": f"未找到区域【{region_name}】（或匹配歧义）"}

    merged = sc.merged_scenes(slot, region) if slot is not None else \
        ((scenes.get("场景", {}) or {}).get(region, {}) or {})
    limit = sc.scene_limit(region, scenes)
    base = set(sc._base_scenes(region, scenes))
    station = (scenes.get("驿站出口", {}) or {}).get(region)
    region_types = sc.merged_types(slot, region, scenes) if slot is not None else \
        sc.merged_types(None, region, scenes)

    entries = []
    orphans = []
    for scene_name, exits in merged.items():
        scene_type = region_types.get(scene_name) if isinstance(region_types, dict) else None
        orphan = not bool(exits)
        if orphan:
            orphans.append(scene_name)
        entries.append({
            "名称": scene_name,
            "来源": "基线" if scene_name in base else "新增",
            "驿站出口": bool(station and scene_name == station),
            "类型": scene_type.get("类型") if isinstance(scene_type, dict) else None,
            "功能NPC": scene_type.get("功能NPC") if isinstance(scene_type, dict) else None,
            "方位出口": dict(exits or {}),
            "孤点": orphan,
        })

    total = len(merged)
    return {
        "区域": region,
        "驿站出口": station,
        "配额": {"上限": limit, "已用": total, "剩余": limit - total},
        "场景": entries,
        "孤点": orphans,
    }


def query_limits():
    """返回全区域场景总量上限。"""
    scenes = sc.load_scenes()
    return {"配额": dict(scenes.get("上限", {}) or {})}


def query_map(region_name, slot=None):
    """地图查询统一入口；``region_name='配额'`` 时返回全区域配额。"""
    if region_name == "配额":
        return query_limits()
    return query_region(region_name, slot)


def _print_region(region, slot):
    scenes = sc.load_scenes()
    merged = sc.merged_scenes(slot, region) if slot is not None else \
        ((scenes.get("场景", {}) or {}).get(region, {}) or {})
    limit = sc.scene_limit(region, scenes)
    base = set(sc._base_scenes(region, scenes))
    overlay = sc.read_overlay(slot).get(region, {}) if slot is not None else {}
    station = (scenes.get("驿站出口", {}) or {}).get(region)

    print(f"【{region}】 驿站出口: {station or '（未设）'}")
    total = len(merged)
    print(f"配额: 上限 {limit}，已用 {total}，剩余 {limit - total}")
    if not merged:
        print("（该区域尚无已登记场景，可用「登记场景」逐步起底）")
        return
    orphans = []
    region_types = sc.merged_types(slot, region, scenes) if slot is not None else \
        sc.merged_types(None, region, scenes)
    print("\n已登记场景（基线/覆盖层）：")
    for scn, exits in merged.items():
        tag = "·基线" if scn in base else "·新增"
        if station and scn == station:
            tag += "·驿站出口"
        entry = region_types.get(scn) if isinstance(region_types, dict) else None
        if entry and entry.get("类型"):
            tag += f"·{entry['类型']}"
            if entry.get("功能NPC"):
                tag += f"({entry['功能NPC']})"
        if not exits:
            tag += "·孤点(无出口)"
            orphans.append(scn)
        ex = " ".join(f"{d}:{nb}" for d, nb in exits.items()) if exits else "—"
        print(f"  {scn}{tag}")
        print(f"      出口: {ex}")
    if orphans:
        print(f"\n孤点场景（无方位出口，待补）: {'、'.join(orphans)}")


def _print_limits():
    scenes = sc.load_scenes()
    limits = scenes.get("上限", {}) or {}
    print("全区域场景配额表（场景总量上限，含基线）：")
    for region in limits:
        print(f"  {region}: {limits[region]}")


def _cli(argv):
    argv = argv or []
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    slot = None
    args = list(argv)
    if "--slot" in args:
        i = args.index("--slot")
        if i + 1 >= len(args):
            print("用法：--slot 须跟 slot 编号", file=sys.stderr)
            return 2
        slot = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    if not args:
        print("用法：map_query.py <区域> [--slot N] | 配额", file=sys.stderr)
        return 2
    if args[0] == "配额":
        _print_limits()
        return 0
    scenes = sc.load_scenes()
    region = _resolve_region(args[0], scenes)
    if region is None:
        print(f"未找到区域【{args[0]}】（或匹配歧义）", file=sys.stderr)
        return 1
    _print_region(region, slot)
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
