#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 assets/data 的基础 schema、索引与跨文件引用。"""

import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "assets" / "data"
EFFECTS_DIR = SKILL_DIR / "scripts" / "effects"
GROUPS = ("characters", "skills", "items", "buffs", "factions")
INDEXED_GROUPS = ("characters", "skills", "items")
DIRECTIONS = {"北", "东北", "东", "东南", "南", "西南", "西", "西北"}
SKILL_TYPES = {"心法", "搏击", "剑法", "刀法", "长兵", "奇门", "暗器"}
SCENE_TYPES = {"驿站", "店铺", "客栈"}

SCHEMAS = {
    "characters": {
        "id": str, "名称": str, "性别": str, "年龄": int, "阵营": str,
        "一级属性": dict, "极性": dict, "武艺": dict, "技艺": dict,
        "人设": str, "经验值": (int, float), "武学": list,
        "携带技能": list, "装备": dict, "物品": list,
        "关系度": (int, float), "死亡": bool, "战斗风格": str,
    },
    "skills": {
        "id": str, "名称": str, "类型": str, "描述": str,
        "品级": int, "等级增益": list,
    },
    "items": {
        "名称": str, "类型": str, "子类型": (str, type(None)),
        "品级": int, "描述": str, "价格": (int, float),
    },
    "buffs": {
        "id": str, "名称": str, "类型": str, "效果": str,
        "叠加方式": str,
    },
    "factions": {
        "名称": str, "描述": str, "地理位置": str,
        "成员": list, "武学": list,
    },
}


class Validator:
    def __init__(self):
        self.errors = []
        self.documents = {}
        self.records = {}

    def error(self, path, message):
        try:
            label = path.relative_to(SKILL_DIR)
        except ValueError:
            label = path
        self.errors.append(f"{label}: {message}")

    def load_all_json(self):
        if not DATA_DIR.is_dir():
            self.error(DATA_DIR, "数据目录不存在")
            return
        for path in sorted(DATA_DIR.rglob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                self.error(path, f"JSON 无法读取：{exc}")
                continue
            if not isinstance(value, dict):
                self.error(path, "顶层必须是 JSON 对象")
                continue
            self.documents[path] = value

    def load_records(self):
        for group in GROUPS:
            base = DATA_DIR / group
            records = {}
            ids = {}
            for path in sorted(base.rglob("*.json")):
                if path.name == "index.json" or path not in self.documents:
                    continue
                record = self.documents[path]
                name = path.stem
                if name in records:
                    self.error(path, f"名称与 {records[name][0].relative_to(DATA_DIR)} 重复：{name}")
                    continue
                records[name] = (path, record)
                self.validate_schema(group, path, record)
                if record.get("名称") != name:
                    self.error(path, f"名称应与文件名一致：{record.get('名称')!r} != {name!r}")
                if group in {"characters", "skills", "buffs"}:
                    record_id = record.get("id")
                    if not isinstance(record_id, str) or not record_id:
                        self.error(path, "id 必须是非空字符串")
                    elif record_id in ids:
                        self.error(path, f"id 与 {ids[record_id].relative_to(DATA_DIR)} 重复：{record_id}")
                    else:
                        ids[record_id] = path
            self.records[group] = records

    def validate_schema(self, group, path, record):
        for field, expected in SCHEMAS[group].items():
            if field not in record:
                self.error(path, f"缺少字段：{field}")
                continue
            value = record[field]
            if not isinstance(value, expected):
                names = expected if isinstance(expected, tuple) else (expected,)
                label = "/".join(item.__name__ for item in names)
                self.error(path, f"字段 {field} 类型应为 {label}，实际为 {type(value).__name__}")

    def validate_indexes(self):
        for group in INDEXED_GROUPS:
            base = DATA_DIR / group
            index_path = base / "index.json"
            index = self.documents.get(index_path)
            if index is None:
                self.error(index_path, "缺少或无法读取索引")
                continue
            actual = {
                name: path.relative_to(base).as_posix()
                for name, (path, _) in self.records.get(group, {}).items()
            }
            for name in sorted(actual.keys() - index.keys()):
                self.error(index_path, f"缺少条目：{name} -> {actual[name]}")
            for name in sorted(index.keys() - actual.keys()):
                self.error(index_path, f"悬空条目：{name} -> {index[name]!r}")
            for name in sorted(actual.keys() & index.keys()):
                if not isinstance(index[name], str):
                    self.error(index_path, f"条目路径必须是字符串：{name}")
                elif index[name] != actual[name]:
                    self.error(index_path, f"路径不一致：{name} -> {index[name]!r}，应为 {actual[name]!r}")

    def validate_references(self):
        characters = self.records.get("characters", {})
        skills = self.records.get("skills", {})
        items = self.records.get("items", {})
        buffs = self.records.get("buffs", {})
        factions = self.records.get("factions", {})
        buff_ids = {
            record.get("id") for _, record in buffs.values()
            if isinstance(record.get("id"), str)
        }

        for name, (path, character) in characters.items():
            faction = character.get("阵营")
            if faction != "散人" and faction not in factions:
                self.error(path, f"阵营不存在：{faction!r}")

            learned = set()
            martial_arts = character.get("武学")
            if isinstance(martial_arts, list):
                for index, entry in enumerate(martial_arts):
                    if not isinstance(entry, dict):
                        self.error(path, f"武学[{index}] 必须是对象")
                        continue
                    skill_name = entry.get("名称")
                    level = entry.get("等级")
                    if not isinstance(skill_name, str):
                        self.error(path, f"武学[{index}].名称 必须是字符串")
                    else:
                        learned.add(skill_name)
                        if skill_name not in skills:
                            self.error(path, f"武学不存在：{skill_name}")
                    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 10:
                        self.error(path, f"武学[{index}].等级 必须是 1-10 的整数")

            carried = character.get("携带技能")
            if isinstance(carried, list):
                for skill_name in carried:
                    if not isinstance(skill_name, str):
                        self.error(path, "携带技能必须全部是字符串")
                    elif skill_name not in skills:
                        self.error(path, f"携带技能不存在：{skill_name}")
                    elif skill_name not in learned:
                        self.error(path, f"携带技能尚未习得：{skill_name}")

            active = character.get("运转心法")
            if active is not None:
                if not isinstance(active, str):
                    self.error(path, "运转心法必须是字符串或 null")
                elif active not in skills:
                    self.error(path, f"运转心法不存在：{active}")
                else:
                    if active not in learned:
                        self.error(path, f"运转心法尚未习得：{active}")
                    if skills[active][1].get("类型") != "心法":
                        self.error(path, f"运转心法类型不是心法：{active}")

            equipment = character.get("装备")
            if isinstance(equipment, dict):
                for slot, item_name in equipment.items():
                    if item_name is not None and not isinstance(item_name, str):
                        self.error(path, f"装备.{slot} 必须是字符串或 null")
                    elif item_name and item_name not in items:
                        self.error(path, f"装备物品不存在：{item_name}")
            for field in ("物品", "携带物品"):
                inventory = character.get(field, [])
                if not isinstance(inventory, list):
                    self.error(path, f"{field} 必须是数组")
                    continue
                for item_name in inventory:
                    if not isinstance(item_name, str):
                        self.error(path, f"{field} 必须全部是字符串")
                    elif item_name not in items:
                        self.error(path, f"{field}引用不存在：{item_name}")

        for _, (path, skill) in skills.items():
            skill_type = skill.get("类型")
            if skill_type not in SKILL_TYPES:
                self.error(path, f"未知武学类型：{skill_type!r}")
            bonuses = skill.get("等级增益")
            levels = []
            if isinstance(bonuses, list):
                for index, entry in enumerate(bonuses):
                    if not isinstance(entry, dict):
                        self.error(path, f"等级增益[{index}] 必须是对象")
                        continue
                    level = entry.get("等级")
                    effect = entry.get("效果")
                    if not isinstance(level, int) or isinstance(level, bool):
                        self.error(path, f"等级增益[{index}].等级 必须是整数")
                    else:
                        levels.append(level)
                    if not isinstance(effect, dict):
                        self.error(path, f"等级增益[{index}].效果 必须是对象")
                if sorted(levels) != list(range(1, 11)):
                    self.error(path, f"等级增益必须完整覆盖 1-10 境，实际为 {sorted(levels)}")
            effect_name = skill.get("技能特效")
            if effect_name is not None:
                if not isinstance(effect_name, str) or not effect_name:
                    self.error(path, "技能特效必须是非空字符串")
                elif not (EFFECTS_DIR / "skills" / f"{effect_name}.py").is_file():
                    self.error(path, f"技能特效脚本不存在：{effect_name}.py")

        for _, (path, item) in items.items():
            skill_name = item.get("武学")
            if skill_name is not None:
                if not isinstance(skill_name, str):
                    self.error(path, "武学引用必须是字符串")
                elif skill_name not in skills:
                    self.error(path, f"武学引用不存在：{skill_name}")
            use_effect = item.get("使用效果")
            if isinstance(use_effect, dict):
                status = use_effect.get("施加状态")
                if isinstance(status, dict):
                    status_id = status.get("id")
                    if status_id not in buff_ids:
                        self.error(path, f"施加状态不存在：{status_id!r}")
            equipment_effect = item.get("装备效果")
            if equipment_effect is not None:
                if not isinstance(equipment_effect, dict):
                    self.error(path, "装备效果必须是对象")
                else:
                    for effect_name in equipment_effect:
                        if not (EFFECTS_DIR / "equipments" / f"{effect_name}.py").is_file():
                            self.error(path, f"装备效果脚本不存在：{effect_name}.py")

        for _, (path, buff) in buffs.items():
            effect_name = buff.get("id")
            if isinstance(effect_name, str) and not (
                    EFFECTS_DIR / "status" / f"{effect_name}.py").is_file():
                self.error(path, f"状态效果脚本不存在：{effect_name}.py")

        for _, (path, faction) in factions.items():
            for member in faction.get("成员", []):
                if not isinstance(member, str):
                    self.error(path, "成员必须全部是字符串")
                elif member not in characters:
                    self.error(path, f"成员不存在：{member}")
            for skill_name in faction.get("武学", []):
                if not isinstance(skill_name, str):
                    self.error(path, "武学必须全部是字符串")
                elif skill_name not in skills:
                    self.error(path, f"武学不存在：{skill_name}")

    def map_nodes(self):
        map_data = self.documents.get(DATA_DIR / "map.json")
        if not map_data:
            return set()
        nodes = map_data.get("节点")
        return set(nodes) if isinstance(nodes, dict) else set()

    def validate_map(self):
        path = DATA_DIR / "map.json"
        data = self.documents.get(path)
        if data is None:
            self.error(path, "缺少或无法读取")
            return
        nodes = data.get("节点")
        adjacency = data.get("邻接")
        if not isinstance(nodes, dict) or not nodes:
            self.error(path, "节点必须是非空对象")
            return
        if not all(isinstance(name, str) and isinstance(kind, str)
                   for name, kind in nodes.items()):
            self.error(path, "节点名称和驿站类型必须是字符串")
        if not isinstance(adjacency, dict):
            self.error(path, "邻接必须是对象")
            return
        node_names = set(nodes)
        if set(adjacency) != node_names:
            self.error(path, "邻接的区域集合必须与节点完全一致")
        for source, edges in adjacency.items():
            if not isinstance(edges, dict):
                self.error(path, f"邻接.{source} 必须是对象")
                continue
            for target, days in edges.items():
                if target not in node_names:
                    self.error(path, f"邻接引用未知区域：{source} -> {target}")
                if (not isinstance(days, (int, float)) or isinstance(days, bool)
                        or days <= 0):
                    self.error(path, f"邻接耗时必须为正数：{source} -> {target}")
                reverse = adjacency.get(target)
                if isinstance(reverse, dict) and reverse.get(source) != days:
                    self.error(path, f"邻接必须双向对称：{source} <-> {target}")
        if node_names:
            seen = set()
            stack = [next(iter(node_names))]
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                edges = adjacency.get(current, {})
                if isinstance(edges, dict):
                    stack.extend(target for target in edges if target in node_names)
            if seen != node_names:
                self.error(path, f"地图不连通，孤立区域：{sorted(node_names - seen)}")

    def validate_scenes(self):
        path = DATA_DIR / "scenes.json"
        data = self.documents.get(path)
        if data is None:
            self.error(path, "缺少或无法读取")
            return
        nodes = self.map_nodes()
        limits = data.get("上限")
        exits = data.get("驿站出口")
        graphs = data.get("场景")
        scene_types = data.get("场景类型", {})
        for label, value in (("上限", limits), ("驿站出口", exits),
                             ("场景", graphs), ("场景类型", scene_types)):
            if not isinstance(value, dict):
                self.error(path, f"{label} 必须是对象")
        if not all(isinstance(value, dict)
                   for value in (limits, exits, graphs, scene_types)):
            return
        for label, value in (("上限", limits), ("驿站出口", exits), ("场景", graphs)):
            if set(value) != nodes:
                self.error(path, f"{label}的区域集合必须与 map.json 节点完全一致")
        for region, limit in limits.items():
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                self.error(path, f"上限.{region} 必须是正整数")
        for region, graph in graphs.items():
            if not isinstance(graph, dict) or not graph:
                self.error(path, f"场景.{region} 必须是非空对象")
                continue
            exit_name = exits.get(region)
            if not isinstance(exit_name, str) or exit_name not in graph:
                self.error(path, f"驿站出口.{region} 未指向该区域场景")
            for scene, edges in graph.items():
                if not isinstance(edges, dict):
                    self.error(path, f"场景.{region}.{scene} 必须是对象")
                    continue
                for direction, target in edges.items():
                    if direction not in DIRECTIONS:
                        self.error(path, f"场景方向无效：{region}.{scene}.{direction}")
                    if not isinstance(target, str) or target not in graph:
                        self.error(path, f"场景出口引用不存在：{region}.{scene} -> {target!r}")
        for region, typed_scenes in scene_types.items():
            if region not in nodes:
                self.error(path, f"场景类型引用未知区域：{region}")
            if not isinstance(typed_scenes, dict):
                self.error(path, f"场景类型.{region} 必须是对象")
                continue
            for scene, info in typed_scenes.items():
                if scene not in graphs.get(region, {}):
                    self.error(path, f"场景类型引用未知场景：{region}.{scene}")
                if not isinstance(info, dict):
                    self.error(path, f"场景类型.{region}.{scene} 必须是对象")
                    continue
                if info.get("类型") not in SCENE_TYPES:
                    self.error(path, f"未知场景类型：{region}.{scene}.{info.get('类型')!r}")
                if not isinstance(info.get("功能NPC"), str) or not info.get("功能NPC"):
                    self.error(path, f"功能NPC 必须是非空字符串：{region}.{scene}")

    def validate_spawn(self):
        path = DATA_DIR / "npc_spawn.json"
        data = self.documents.get(path)
        if data is None:
            self.error(path, "缺少或无法读取")
            return
        characters = self.records.get("characters", {})
        nodes = self.map_nodes()
        for name, region in data.items():
            if name.startswith("_"):
                continue
            if name not in characters:
                self.error(path, f"引用未知角色：{name}")
            if not isinstance(region, str):
                self.error(path, f"角色区域必须是字符串：{name}")
            elif region and region not in nodes:
                self.error(path, f"引用未知区域：{name} -> {region}")

    def run(self):
        self.load_all_json()
        self.load_records()
        self.validate_indexes()
        self.validate_map()
        self.validate_scenes()
        self.validate_spawn()
        self.validate_references()
        return not self.errors


def main():
    validator = Validator()
    if not validator.run():
        print(f"数据完整性校验失败：{len(validator.errors)} 项", file=sys.stderr)
        for error in validator.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    counts = ", ".join(
        f"{group}={len(validator.records.get(group, {}))}"
        for group in GROUPS
    )
    print(f"数据完整性校验通过：JSON={len(validator.documents)}，{counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
