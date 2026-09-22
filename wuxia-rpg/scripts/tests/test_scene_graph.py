#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景覆盖层隔离与重连语义。"""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from world import scene  # noqa: E402


class SceneGraphTest(unittest.TestCase):
    def setUp(self):
        self.scenes = {
            "上限": {"测试区": 8},
            "场景": {"测试区": {
                "场景": ["甲地", "乙地", "丁地"],
                "边": [["甲地.北", "乙地.南"], ["乙地.东", "丁地.西"]],
            }},
            "场景类型": {},
        }
        self.overlay = {}
        self.patches = [
            patch("world.scene.load_scenes", return_value=self.scenes),
            patch("world.scene.read_overlay", side_effect=lambda slot: copy.deepcopy(self.overlay)),
            patch("world.scene.write_overlay", side_effect=self._write_overlay),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def _write_overlay(self, slot, data):
        self.overlay = copy.deepcopy(data)

    def test_isolate_removes_baseline_edges_both_ways(self):
        staged = {}
        result = scene.isolate_scene(
            1, {"类型": "隔离地点", "区域": "测试区", "场景": "甲地"}, staged
        )
        self.assertTrue(result["ok"], result)
        scene.commit_staged(1, staged)
        merged = scene.merged_scenes(1, "测试区")
        self.assertEqual(merged["甲地"], {})
        self.assertNotIn("南", merged["乙地"])
        self.assertEqual(merged["乙地"].get("东"), "丁地")

    def test_same_batch_isolate_then_register_replaces_old_path(self):
        staged = {}
        isolated = scene.isolate_scene(
            1, {"类型": "隔离地点", "区域": "测试区", "场景": "甲地"}, staged
        )
        registered = scene.register_scene(1, {
            "类型": "登记场景", "区域": "测试区", "场景": "甲地",
            "方位出口": {"东": "丙地"},
        }, staged, {}, known_targets={"丙地"})
        self.assertTrue(isolated["ok"] and registered["ok"], (isolated, registered))
        scene.commit_staged(1, staged)
        merged = scene.merged_scenes(1, "测试区")
        self.assertEqual(merged["甲地"], {"东": "丙地"})
        self.assertNotIn("南", merged["乙地"])
        self.assertEqual(merged["丙地"], {"西": "甲地"})

    def test_unknown_region_and_unregistered_target_are_rejected(self):
        staged = {}
        bad_region = scene.register_scene(
            1, {"类型": "登记场景", "区域": "不存在区", "场景": "戊地"}, staged)
        self.assertFalse(bad_region["ok"])
        self.assertIn("未知区域", bad_region["msg"])

        bad_isolate = scene.isolate_scene(
            1, {"类型": "隔离地点", "区域": "不存在区", "场景": "甲地"}, staged)
        self.assertFalse(bad_isolate["ok"])
        self.assertIn("未知区域", bad_isolate["msg"])

        bad_target = scene.register_scene(1, {
            "类型": "登记场景", "区域": "测试区", "场景": "戊地",
            "方位出口": {"北": "凭空地点"},
        }, staged)
        self.assertFalse(bad_target["ok"])
        self.assertIn("未登记", bad_target["msg"])

        # 同批次前向引用：known_targets 放行（批次内 A↔B 任意书写顺序）
        forward = scene.register_scene(1, {
            "类型": "登记场景", "区域": "测试区", "场景": "戊地",
            "方位出口": {"北": "己地"},
        }, staged, known_targets={"己地"})
        self.assertTrue(forward["ok"], forward)
        scene.commit_staged(1, staged)
        merged = scene.merged_scenes(1, "测试区")
        self.assertEqual(merged["戊地"], {"北": "己地"})
        self.assertEqual(merged["己地"], {"南": "戊地"})

    def test_direction_slot_conflict_on_target_rejected(self):
        # 方位槽唯一：乙地.南 已被甲地占用，戊地.北=乙地 须打回
        staged = {}
        result = scene.register_scene(1, {
            "类型": "登记场景", "区域": "测试区", "场景": "戊地",
            "方位出口": {"北": "乙地"},
        }, staged)
        self.assertFalse(result["ok"], result)
        self.assertIn("南方已连通", result["msg"])

    def test_scene_name_with_dot_rejected(self):
        staged = {}
        result = scene.register_scene(1, {
            "类型": "登记场景", "区域": "测试区", "场景": "带.点地点",
        }, staged)
        self.assertFalse(result["ok"], result)
        self.assertIn("不得包含", result["msg"])


class LegacyOverlayMigrationTest(unittest.TestCase):
    """旧格式覆盖层（每场景 {方位:邻}，含替换标记）读入即迁移为边表。"""

    def setUp(self):
        self.scenes = {
            "上限": {"测试区": 8},
            "场景": {"测试区": {
                "场景": ["甲地", "乙地", "丁地"],
                "边": [["甲地.北", "乙地.南"], ["乙地.东", "丁地.西"]],
            }},
            "场景类型": {},
        }
        self.raw = {"测试区": {
            "新点": {"__完整替换__": True, "北": "甲地"},
            "甲地": {"__完整替换__": True, "南": "新点", "北": "乙地"},
        }}
        self.patches = [
            patch("world.scene.load_scenes", return_value=self.scenes),
            patch("world.scene.sm.read_map_overlay", return_value=self.raw),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_replace_mark_becomes_removed_baseline_edges(self):
        overlay = scene.read_overlay(1)
        entry = overlay["测试区"]
        self.assertIn("新点", entry["场景"])
        self.assertIn("甲地", entry["场景"])
        self.assertTrue(any(set(e) == {"新点.北", "甲地.南"} for e in entry["边"]),
                        entry["边"])
        # 甲地为替换态：基线触及边 [甲地.北, 乙地.南] 进删边，声明边 [甲地.北, 乙地.南] 复活
        self.assertTrue(any(set(e) == {"甲地.北", "乙地.南"} for e in entry.get("删边", [])),
                        entry.get("删边"))
        self.assertTrue(any(set(e) == {"甲地.北", "乙地.南"} for e in entry["边"]),
                        entry["边"])

    def test_merged_view_after_migration(self):
        merged = scene.merged_scenes(1, "测试区")
        self.assertEqual(merged["甲地"], {"南": "新点", "北": "乙地"})
        self.assertEqual(merged["新点"], {"北": "甲地"})
        self.assertEqual(merged["乙地"], {"南": "甲地", "东": "丁地"})

    def test_register_on_migrated_overlay(self):
        staged = {}
        result = scene.register_scene(1, {
            "类型": "登记场景", "区域": "测试区", "场景": "再点",
            "方位出口": {"南": "甲地"},
        }, staged, known_targets=set())
        # 甲地.北 已被乙地占用 → 再点.南=甲地 要求甲地.北 空闲，应打回
        self.assertFalse(result["ok"], result)
        result = scene.register_scene(1, {
            "类型": "登记场景", "区域": "测试区", "场景": "再点",
            "方位出口": {"东南": "甲地"},
        }, staged)
        self.assertTrue(result["ok"], result)
        merged = scene.merged_scenes(1, "测试区")
        # 尚未 commit：暂存登记不进磁盘层视图
        self.assertEqual(merged.get("再点"), None)


if __name__ == "__main__":
    unittest.main()
