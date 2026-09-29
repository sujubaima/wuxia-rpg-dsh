#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基础数据校验器的场景边表规则。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import validate_data  # noqa: E402


class SceneDataValidationTest(unittest.TestCase):
    def validate_scenes(self, scene_data):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            map_path = data_dir / "map.json"
            scenes_path = data_dir / "scenes.json"
            validator = validate_data.Validator()
            validator.documents = {
                map_path: {"节点": {"测试区": "驿站"}, "邻接": {"测试区": {}}},
                scenes_path: scene_data,
            }
            with patch.object(validate_data, "DATA_DIR", data_dir):
                validator.validate_scenes()
            return validator.errors

    def baseline(self, names=None, edges=None):
        return {
            "上限": {"测试区": 8},
            "驿站出口": {"测试区": "水驿"},
            "场景": {"测试区": {
                "场景": names or ["水驿", "街市", "客栈"],
                "边": edges if edges is not None else [
                    ["水驿.东", "街市.西"],
                    ["街市.北", "客栈.南"],
                ],
            }},
            "场景类型": {"测试区": {
                "水驿": {"类型": "驿站", "功能NPC": "驿丞"},
                "客栈": {"类型": "客栈", "功能NPC": "掌柜"},
            }},
        }

    def test_current_scene_list_and_edge_table_pass(self):
        self.assertEqual(self.validate_scenes(self.baseline()), [])

    def test_scene_names_must_be_unique_nonempty_strings(self):
        errors = self.validate_scenes(self.baseline(
            names=["水驿", "街市", "街市", ""], edges=[]))
        self.assertTrue(any("必须是非空字符串" in error for error in errors), errors)
        self.assertTrue(any("不得包含重复名称" in error for error in errors), errors)

    def test_edges_must_reference_declared_distinct_scenes_with_reverse_directions(self):
        errors = self.validate_scenes(self.baseline(edges=[
            ["水驿.东", "未知地.西"],
            ["水驿.北", "水驿.南"],
            ["街市.东", "客栈.北"],
            ["无效端点", "客栈.南"],
        ]))
        self.assertTrue(any("引用未声明场景" in error for error in errors), errors)
        self.assertTrue(any("不得连接同一场景" in error for error in errors), errors)
        self.assertTrue(any("两端方位必须互为反向" in error for error in errors), errors)
        self.assertTrue(any("端点须为 场景名.方位" in error for error in errors), errors)

    def test_edges_cannot_repeat_or_reuse_a_direction(self):
        errors = self.validate_scenes(self.baseline(edges=[
            ["水驿.东", "街市.西"],
            ["街市.西", "水驿.东"],
            ["水驿.东", "客栈.西"],
        ]))
        self.assertTrue(any("与已有边重复" in error for error in errors), errors)
        self.assertTrue(any("端点已被其他边占用：水驿.东" in error for error in errors), errors)

    def test_exit_and_scene_types_use_declared_scene_list(self):
        data = self.baseline(edges=[])
        data["驿站出口"]["测试区"] = "不存在"
        data["场景类型"]["测试区"]["不存在"] = {
            "类型": "店铺", "功能NPC": "掌柜",
        }
        errors = self.validate_scenes(data)
        self.assertTrue(any("驿站出口.测试区 未指向该区域场景" in error
                            for error in errors), errors)
        self.assertTrue(any("场景类型引用未知场景：测试区.不存在" in error
                            for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
