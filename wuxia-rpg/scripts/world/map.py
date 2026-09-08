#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大世界区域拓扑寻路：据 assets/data/map.json 的邻接表算始发地→目的地的最短路径与耗时。

用法：
  python3 scripts/map.py <始发> <目的地>
  python3 scripts/map.py 路径 <始发> <目的地>   # 同上（显式子命令）
  python3 scripts/map.py 区域                    # 列全部区域
  python3 scripts/map.py 邻接 <区域>            # 列某区域的相邻区域及耗时

区域名支持模糊匹配（子串或去"城/山/海岛"等后缀），如 "长沙" 匹配 "长沙城"。
返回 JSON：{"路径": [...], "耗时": N, "途径": [...]}；不可达返回 {"错误": "..."}。
"""
import heapq
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from common.json_io import read_json

MAP_PATH = os.path.join(HERE, "..", "assets", "data", "map.json")


def _load_map():
    return read_json(MAP_PATH, expected_type=dict)


def _resolve(name, nodes):
    """区域名模糊匹配：精确 → 子串 → 去'城/山/海岛/湖/港'等后缀再匹配。"""
    if name in nodes:
        return name
    # 子串匹配
    hits = [n for n in nodes if name in n]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return None  # 歧义，交由调用方处理
    # 去"城/山/海岛/湖/港/关中"等后缀反向匹配
    suffixes = ("城", "山", "海岛", "湖", "港", "·关中", "·洞庭湖", "·兰州")
    stripped = name
    for s in suffixes:
        if stripped.endswith(s):
            stripped = stripped[: -len(s)]
    if stripped and stripped != name:
        hits = [n for n in nodes if stripped in n or n in stripped]
        if len(hits) == 1:
            return hits[0]
    return None


def shortest_path(src, dst):
    """Dijkstra 最短路径。返回 {"路径": [...], "耗时": N} 或 {"错误": ...}。"""
    m = _load_map()
    nodes = m.get("节点", {})
    adj = m.get("邻接", {})
    s = _resolve(src, nodes)
    d = _resolve(dst, nodes)
    if s is None:
        return {"错误": f"未找到始发地【{src}】（或匹配歧义）"}
    if d is None:
        return {"错误": f"未找到目的地【{dst}】（或匹配歧义）"}
    if s == d:
        return {"路径": [s], "耗时": 0}
    # Dijkstra
    dist = {s: 0}
    prev = {}
    pq = [(0, s)]
    while pq:
        cur_dist, cur = heapq.heappop(pq)
        if cur == d:
            break
        if cur_dist > dist.get(cur, float("inf")):
            continue
        for nb, w in adj.get(cur, {}).items():
            nd = cur_dist + int(w)
            if nd < dist.get(nb, float("inf")):
                dist[nb] = nd
                prev[nb] = cur
                heapq.heappush(pq, (nd, nb))
    if d not in dist:
        return {"错误": f"【{s}】与【{d}】不连通"}
    # 回溯路径
    path = [d]
    while path[-1] != s:
        path.append(prev[path[-1]])
    path.reverse()
    return {"路径": path, "耗时": dist[d]}


def _cli(argv):
    m = _load_map()
    nodes = m.get("节点", {})
    adj = m.get("邻接", {})
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "区域":
        # 列出每个区域的可达列表（A: [B, C, D]）
        for n in nodes:
            routes = list(adj.get(n, {}).keys())
            print(f"{n}: {routes}")
        return 0
    if cmd == "邻接":
        if len(argv) < 2:
            print("用法：map.py 邻接 <区域>", file=sys.stderr)
            return 2
        name = _resolve(argv[1], nodes)
        if not name:
            print(f"未找到区域【{argv[1]}】", file=sys.stderr)
            return 1
        nbrs = adj.get(name, {})
        print(f"{name} 相邻区域：")
        for nb, w in nbrs.items():
            print(f"  → {nb}　{w}天")
        return 0
    # 默认：寻路（支持可选 "路径" 子命令）
    if cmd == "路径":
        argv = argv[1:]
    if len(argv) < 2:
        print("用法：map.py <始发> <目的地>", file=sys.stderr)
        return 2
    result = shortest_path(argv[0], argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if "错误" not in result else 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
