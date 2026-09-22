#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性转换：scenes.json 场景邻接从「每场景 {方位:邻} dict + 镜像成对」转为
「区域级边表，每条边双方位内联 ["场景名.方位", "场景名.方位"]」。

- 成对双向边合并为一条（两侧声明的方位直接内联）；
- 单向边缺失侧的反向方位显式物化（转换后无隐式信息）；
- 7 处反向槽位被占的冲突边，改占目标节点的空闲斜方位（优先原方位相邻的对角）。

自校验（任一不过即拒绝落盘）：
1. 无重边/自环；2. 边端点全在场景列表；3. 每边两侧方位互为反向；
4. 每节点方位槽唯一；5. 28 区域新旧无向边集合逐一相等（连通性完整保持）。

用法：
  python3 scripts/convert_scenes.py            # 试运行：输出报告与校验结果，不写盘
  python3 scripts/convert_scenes.py --write    # 校验全过后备份原文并写盘
"""
import copy
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENES_PATH = os.path.normpath(os.path.join(HERE, "..", "assets", "data", "scenes.json"))

COMPASS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
REVERSE = {"北": "南", "南": "北", "东": "西", "西": "东",
           "东北": "西南", "西南": "东北", "东南": "西北", "西北": "东南"}

# 手工修复（自校验暴露的三类基线缺陷 + 与用户定稿的金陵方位）：
#   del: 删除该方位声明；move: 同一目标改方位；add: 新增声明（单侧声明由转换物化反向）。
MANUAL_EDITS = [
    # 杭州：断桥与九溪路口互称对方在北（成对矛盾）；九溪实在断桥西南——合于实地理
    ("杭州", "西湖断桥", "del", "北", None, None),
    ("杭州", "九溪路口", "move", "北", "东北", None),
    # 金陵：秦淮河畔南槽被乌衣巷占（用户定稿：聚宝门占东南——合于实地理）
    ("金陵", "聚宝门", "del", "北", None, None),
    ("金陵", "秦淮河畔", "add", "东南", None, "聚宝门"),
    # 北京：正阳门外/广渠陆驿/燕赵镖局三角方向互相矛盾；按实地理重组
    ("北京", "正阳门外", "move", "南", "东南", None),   # 广渠陆驿在前门东南
    ("北京", "广渠陆驿", "del", "西", None, None),      # 与上矛盾的一侧
    ("北京", "燕赵镖局", "del", "南", None, None),      # 南槽改让广渠陆驿
    ("北京", "燕赵镖局", "move", "东", "南", None),     # 与 广渠陆驿.北=燕赵镖局 成对（北/南）
    ("北京", "正阳门外", "add", "东北", None, "燕赵镖局"),
    # 长沙：湘江渡东槽跨边冲突（岳麓书院自有声明 vs 橘渚水驿推导）；橘渚水驿改下游方向
    ("长沙", "橘渚水驿", "move", "西", "西北", None),
]

# 6 处冲突边：声明侧 (S, d, T)——T 的 reverse(d) 槽已被其他场景占用，无法成对。
# 修法：改在 T 上占一个空闲方位 c（优先 reverse(d) 相邻的对角），要求 S 的 reverse(c) 也空闲。
CONFLICT_EDGES = [
    ("临清", "土桥镇", "南", "运河码头"),
    ("长沙", "丐帮分舵", "东", "坡子街"),
    ("广州", "南少林接引", "北", "十三行"),
    ("南洋海岛", "土人村落", "北", "椰林滩"),
    ("庐山", "东林寺", "西", "牯岭"),
    ("河西（兰州）", "茶马市", "北", "黄河渡口"),
]

NEW_DESC = (
    "区域内场景图基线数据。上限=每区域GM可新增场景上限（基线场景不计入额度）。"
    "场景=各区域 {场景:[场景名...], 边:[[\"场景名.方位\",\"场景名.方位\"],...]}——"
    "每条边双方位内联且互为反向；每场景每方位至多一个邻接点；"
    "在场景列表但不出现在任何边中者为孤点（仍占配额）。"
    "驿站出口=该区域出城所经驿站场景名。"
    "场景类型=功能性场景的{类型(驿站/店铺/客栈),功能NPC(身份名)}，"
    "用于engine校验功能入口与功能NPC必露脸红线；缺省无类型=普通场景。"
    "覆盖层 map_overlay.json/scene_types_overlay.json 存GM运行时新增场景（边/类型），"
    "渲染取基线∪覆盖层。各区域基线据其门派/势力/风土设计，体现地域差异。"
    "每区域基线必含驿站与客栈（住宿歇脚处）。"
)


def _adjacent_diagonals(direction):
    """方位的左右相邻对角，按罗盘顺序。如 南 → [东南, 西南]。"""
    i = COMPASS.index(direction)
    return [COMPASS[(i + 1) % 8], COMPASS[(i - 1) % 8]]


def _fix_directions(region_scenes, declared_s, declared_d, target):
    """为冲突边选目标节点的新方位：优先原方位相邻对角，其次原方位，再次罗盘序。"""
    slots = {d: nb for nb, ex in region_scenes.items() for d, nb in (ex or {}).items()
             if nb == declared_s}  # 目标节点当前被声明侧占用的方位
    target_exits = region_scenes.get(target) or {}
    candidates = _adjacent_diagonals(REVERSE[declared_d]) + [REVERSE[declared_d]] + \
        [d for d in COMPASS if d not in _adjacent_diagonals(REVERSE[declared_d])]
    source_exits = region_scenes.get(declared_s) or {}
    for c in candidates:
        if c in target_exits:
            continue  # 目标节点该方位已被占用
        if REVERSE[c] in source_exits:
            continue  # 声明侧的反向槽也须空闲
        return c
    return None


def convert(scenes):
    """转换全部区域；返回 (新数据, 报告行列表, 错误列表)。"""
    errors = []
    report = []
    new_regions = {}
    fix_log = []

    for region, old in scenes["场景"].items():
        work = copy.deepcopy(old)
        # 0) 手工修复：三类自校验暴露的基线缺陷（成对矛盾/跨边槽位冲突/金陵定稿方位）
        for r, scn, op, d_old, d_new, target in MANUAL_EDITS:
            if r != region:
                continue
            exits = work.setdefault(scn, {})
            if op == "del":
                if exits.get(d_old) is None:
                    errors.append(f"{region}：手工修复失效，{scn}.{d_old} 不存在")
                else:
                    del exits[d_old]
            elif op == "move":
                if d_old not in exits:
                    errors.append(f"{region}：手工修复失效，{scn}.{d_old} 不存在")
                elif d_new in exits:
                    errors.append(f"{region}：手工修复失效，{scn}.{d_new} 已被占用")
                else:
                    exits[d_new] = exits.pop(d_old)
            elif op == "add":
                if d_old in exits:
                    errors.append(f"{region}：手工修复失效，{scn}.{d_old} 已被占用")
                else:
                    exits[d_old] = target
        # 1) 冲突边改方位：删原声明，记录新声明（目标侧声明）
        for r, s, d, t in CONFLICT_EDGES:
            if r != region:
                continue
            if (work.get(s) or {}).get(d) != t:
                errors.append(f"{region}：冲突边声明不符（{s}.{d}≠{t}），修法表过期")
                continue
            c = _fix_directions(work, s, d, t)
            if c is None:
                errors.append(f"{region}：{s}-{t} 无可用空闲方位")
                continue
            del work[s][d]
            work.setdefault(t, {})[c] = s
            fix_log.append((region, s, d, t, c, REVERSE[c]))

        # 2) 组边：一次遍历收集声明，成对边合并，单向边物化反向
        edges = {}       # pair -> (label_a, label_b)
        declared = {}    # pair -> (node, dir) 首个声明
        for a, exits in work.items():
            for d, b in (exits or {}).items():
                if b not in work:
                    errors.append(f"{region}：{a}.{d} 指向未登记场景【{b}】")
                    continue
                if a == b:
                    errors.append(f"{region}：自环边 {a}")
                    continue
                pair = tuple(sorted((a, b)))
                if pair in edges:
                    errors.append(f"{region}：边 {a}-{b} 声明超过两侧")
                    continue
                if pair in declared:
                    n0, d0 = declared[pair]
                    if n0 == a:
                        errors.append(f"{region}：{a} 对 {b} 有多个方位声明")
                        continue
                    if REVERSE[d0] != d:
                        errors.append(f"{region}：边 {a}-{b} 两侧方位 {d0}/{d} 不互为反向")
                    edges[pair] = (f"{n0}.{d0}", f"{a}.{d}")
                else:
                    declared[pair] = (a, d)
        for pair, (n0, d0) in declared.items():
            if pair in edges:
                continue
            other = pair[1] if pair[0] == n0 else pair[0]
            edges[pair] = (f"{n0}.{d0}", f"{other}.{REVERSE[d0]}")  # 单向边：物化反向

        # 3) 序列化：场景列表保持原键序，边按 pair 排序稳定输出
        new_regions[region] = {
            "场景": list(work.keys()),
            "边": [list(edges[p]) for p in sorted(edges)],
        }
        report.append(f"{region}: 场景 {len(work)}，边 {len(edges)}（旧声明 "
                      f"{sum(len(ex or {}) for ex in work.values())} 条）")

    # 4) 全局自校验
    for region, data in new_regions.items():
        names = set(data["场景"])
        seen_pairs = set()
        node_dir = {}  # (节点, 方位) -> 邻
        for edge in data["边"]:
            if len(edge) != 2:
                errors.append(f"{region}：边 {edge} 不是两端点")
                continue
            parsed = []
            for label in edge:
                if label.count(".") != 1:
                    errors.append(f"{region}：边标签 {label} 须为 场景名.方位（各含一个点）")
                    parsed = None
                    break
                n, d = label.rsplit(".", 1)
                if d not in REVERSE:
                    errors.append(f"{region}：边标签 {label} 方位非法")
                    parsed = None
                    break
                if n not in names:
                    errors.append(f"{region}：边端点 {n} 不在场景列表")
                    parsed = None
                    break
                parsed.append((n, d))
            if not parsed:
                continue
            (na, da), (nb, db) = parsed
            if na == nb:
                errors.append(f"{region}：自环边 {edge}")
                continue
            if REVERSE[da] != db:
                errors.append(f"{region}：边 {edge} 两侧方位不互为反向")
                continue
            pair = tuple(sorted((na, nb)))
            if pair in seen_pairs:
                errors.append(f"{region}：重边 {na}-{nb}")
                continue
            seen_pairs.add(pair)
            for n, d, other in ((na, da, nb), (nb, db, na)):
                key = (n, d)
                if key in node_dir and node_dir[key] != other:
                    errors.append(f"{region}：{n} 的{d}方位同时邻接 {node_dir[key]} 与 {other}")
                node_dir[key] = other
        # 5) 新旧无向边集合相等（连通性完整保持）
        old_pairs = set()
        for a, exits in scenes["场景"][region].items():
            for b in (exits or {}).values():
                if b in scenes["场景"][region]:
                    old_pairs.add(tuple(sorted((a, b))))
        if old_pairs != seen_pairs:
            errors.append(f"{region}：边集合不等 丢失={sorted(old_pairs - seen_pairs)} "
                          f"新增={sorted(seen_pairs - old_pairs)}")

    for region, s, d, t, c, rev_c in fix_log:
        report.append(f"冲突修复 {region}：原 {s}.{d}={t} → {t}.{c}={s}"
                      f"（边 [{t}.{c}, {s}.{rev_c}]）")
    return new_regions, report, errors


def main(argv):
    scenes = json.loads(open(SCENES_PATH, encoding="utf-8").read())
    new_regions, report, errors = convert(scenes)
    print("\n".join(report))
    if errors:
        print("\n校验失败，拒绝落盘：")
        for e in errors:
            print("  ✗", e)
        return 1
    print("\n全部校验通过 ✓")
    if "--write" not in argv:
        print("（试运行，未写盘；加 --write 落盘）")
        return 0
    backup = SCENES_PATH + ".backup-" + "20260922"
    shutil.copy2(SCENES_PATH, backup)
    out = copy.deepcopy(scenes)
    out["_说明"] = NEW_DESC
    out["场景"] = new_regions
    with open(SCENES_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"已写盘 {SCENES_PATH}（备份：{os.path.basename(backup)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
