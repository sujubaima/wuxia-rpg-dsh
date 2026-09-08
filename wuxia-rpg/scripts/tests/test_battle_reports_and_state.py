#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战报结构、序列化、ATB、逃跑胜负与AI候选回归。"""
import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import ai_styles
from combat import battle as report
from combat import battle_engine as be
from common import status_manager as sm


SWORD = "八面玉具剑"


def make_char(name="甲", team="我方", hp=1000, mp=1000, speed=100, charge=0):
    attrs = {
        "气血上限": 1000, "内力上限": 1000,
        "攻击力": 150, "防御力": 120, "精准": 120, "识破": 120,
        "暴击": 80, "速度": speed,
        "力道": 30, "根骨": 30, "内功": 30, "身法": 30,
        "休息气血恢复": 0, "休息内力恢复": 0.1,
    }
    return {
        "名称": name, "阵营": team, "气血": hp, "内力": mp,
        "气血上限": 1000, "内力上限": 1000,
        "状态效果": [], "二级属性": attrs,
        "一级属性": {"力道": 30, "根骨": 30, "内功": 30, "身法": 30},
        "武艺": {"剑法": 10, "刀法": 10, "长兵": 10,
                 "奇门": 10, "暗器": 10, "搏击": 10},
        "武学": [], "携带武学": [], "携带物品": [],
        "冷却": {}, "充能": charge, "装备": {}, "物品": [],
    }


def deterministic_roll(a, b):
    return 1.0 if b <= 1.05 else 99


class BattleReportTest(unittest.TestCase):
    def test_qiangming_and_routed_dot_have_visible_report_clauses(self):
        skill_result = {
            "行动者": "甲", "指令": "武学", "技能": "仁剑义剑", "目标": "乙",
            "闪避": False, "暴击": False, "伤害": 999,
            "行动者内力变化": {"原值": 1000, "新值": 880},
            "目标气血变化": {"原值": 500, "新值": 1},
            "强命保命": [{"目标": "乙", "名称": "强命", "id": "qiangming"}],
        }
        text = report.render_turn(1, skill_result, be.load_skills())
        self.assertIn("乙由【强命】护住最后1点气血", text)
        self.assertIn("失去【强命】状态", text)
        structured = report.struct_turn_entry(1, skill_result, skills_db=be.load_skills())
        self.assertEqual(structured["强命保命"][0]["目标"], "乙")

        dot_result = {
            "行动者": "甲", "指令": "休息", "恢复气血": 0, "恢复内力": 0,
            "气血变化": {"原值": 500, "新值": 500},
            "内力变化": {"原值": 300, "新值": 300},
            "持续伤害": [{"目标": "甲", "数值": 0, "原值": 500, "新值": 500,
                          "改扣内力": 20, "内力原值": 300, "内力新值": 280,
                          "来源": "外伤"}],
        }
        text = report.render_turn(2, dot_result, be.load_skills())
        self.assertIn("【外伤】持续流血", text)
        self.assertIn("耗损20点内力", text)
        self.assertIn("内力 300→280", text)

    def test_cooldown_change_is_visible_and_structured(self):
        result = {
            "行动者": "甲", "指令": "武学", "技能": "九宫八卦剑", "目标": "乙",
            "闪避": False, "暴击": False, "伤害": 100,
            "目标气血变化": {"原值": 500, "新值": 400},
            "冷却变化": [{
                "目标": "乙", "武学": "同归剑法", "原值": 0, "新值": 2,
                "新增冷却": True,
            }],
        }
        text = report.render_turn(2, result, be.load_skills())
        self.assertIn("乙【同归剑法】进入1回合冷却", text)
        structured = report.struct_turn_entry(2, result, skills_db=be.load_skills())
        self.assertEqual(structured["冷却变化"][0]["武学"], "同归剑法")

    def test_status_transfer_is_visible_and_structured(self):
        result = {
            "行动者": "甲", "指令": "武学", "技能": "玉女素心剑", "目标": "乙",
            "闪避": False, "暴击": False, "伤害": 100,
            "目标气血变化": {"原值": 500, "新值": 400},
            "状态转移": [{
                "id": "broken_tendon", "名称": "断筋",
                "来源目标": "甲", "转移目标": "乙", "持续时间": 3,
            }],
        }
        text = report.render_turn(2, result, be.load_skills())
        self.assertIn("将自身【断筋】转予乙", text)
        self.assertIn("甲 失去【断筋】状态", text)
        self.assertIn("乙 气血 500→400，获得3回合【断筋】状态", text)
        structured = report.struct_turn_entry(2, result, skills_db=be.load_skills())
        self.assertEqual(structured["状态转移"][0]["名称"], "断筋")

    def test_aoe_structured_report_preserves_target_special_results(self):
        result = {
            "行动者": "甲", "指令": "武学", "技能": "打狗棒法", "目标": "敌方全体",
            "目标结算": [
                {"目标": "乙", "闪避": True},
                {"目标": "丙", "闪避": False, "暴击": False, "伤害": 120,
                 "目标气血变化": {"原值": 500, "新值": 380},
                 "霸体抵挡": {"目标": "丙", "名称": "霸体"}},
            ],
            "行动者内力变化": {"原值": 1000, "新值": 714},
        }
        entry = report.struct_turn_entry(3, result, is_player=False, skills_db=be.load_skills())
        self.assertEqual(entry["操控"], "AI")
        self.assertTrue(entry["目标结算"][0]["闪避"])
        self.assertEqual(entry["目标结算"][1]["伤害"], 120)
        self.assertEqual(entry["目标结算"][1]["霸体抵挡"]["名称"], "霸体")
        json.dumps(entry, ensure_ascii=False)

    def test_real_process_turn_result_is_json_serializable(self):
        actor = make_char()
        actor["装备"] = {"武器1": SWORD}
        target = make_char("乙", "敌方", hp=1)
        skill = be.load_skills().get("仁剑义剑")
        state = {"角色列表": [actor, target], "回合数": 0, "当前行动者": actor["名称"]}
        with patch.object(be.random, "uniform", side_effect=deterministic_roll), \
                patch.object(be, "_resolve_target_effect",
                             return_value=(True, {"类型": "独立", "发动": True})):
            turn = be.process_turn(state, {"类型": "武学", "技能": skill,
                                           "目标": target["名称"]})
        encoded = json.dumps(turn, ensure_ascii=False)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["结算"]["强命保命"][0]["目标"], "乙")
        self.assertEqual(decoded["结算"]["目标气血变化"]["新值"], 1)


class AtbAndOutcomeTest(unittest.TestCase):
    def test_advance_atb_prioritizes_charge_then_speed(self):
        slow = make_char("慢", speed=50, charge=150)
        fast = make_char("快", speed=100, charge=120)
        actor = be.advance_atb([slow, fast])
        self.assertIs(actor, slow)
        self.assertEqual(slow["充能"], 50)
        self.assertEqual(fast["充能"], 120)

        slow["充能"] = fast["充能"] = 100
        actor = be.advance_atb([slow, fast])
        self.assertIs(actor, fast)
        self.assertEqual(fast["充能"], 0)

    def test_advance_ticks_when_none_ready_and_prediction_is_pure(self):
        slow = make_char("慢", speed=50)
        fast = make_char("快", speed=100)
        actor = be.advance_atb([slow, fast])
        self.assertIs(actor, fast)
        self.assertAlmostEqual(fast["充能"], 100 / 3)
        self.assertAlmostEqual(slow["充能"], 50 + 100 / 3)

        before = [(c["名称"], c["充能"]) for c in (slow, fast)]
        order = be.predict_action_order([slow, fast], count=6)
        self.assertEqual(len(order), 6)
        self.assertTrue(set(order) <= {"慢", "快"})
        self.assertEqual([(c["名称"], c["充能"]) for c in (slow, fast)], before)

    def test_escape_success_clears_only_escaper_battle_status(self):
        actor = make_char()
        enemy = make_char("乙", "敌方")
        sm.apply_status(actor, "iron_wall", 2)
        sm.apply_status(actor, "swift", 5, scene="大世界")
        state = {"角色列表": [actor, enemy], "回合数": 3, "当前行动者": actor["名称"]}
        with patch.object(be.ck, "run_check", return_value={"结果": "成功"}):
            result = be.attempt_escape(state, actor["名称"])
        self.assertTrue(result["逃跑成功"])
        self.assertTrue(actor["逃走"])
        self.assertEqual([(e["id"], e["场景"]) for e in actor["状态效果"]],
                         [("swift", "大世界")])
        self.assertIsNone(result["战斗结束"])
        self.assertEqual(be.check_battle_end([actor, enemy]), "敌方")

    def test_escape_failure_and_mixed_defeat_escape_victory(self):
        actor = make_char()
        ally = make_char("丙")
        enemy = make_char("乙", "敌方")
        state = {"角色列表": [actor, ally, enemy], "回合数": 2,
                 "当前行动者": actor["名称"]}
        with patch.object(be.ck, "run_check", return_value={"结果": "失败"}):
            result = be.attempt_escape(state, actor["名称"])
        self.assertFalse(result["逃跑成功"])
        self.assertFalse(actor.get("逃走", False))
        self.assertEqual(actor["充能"], 0)

        actor["逃走"] = True
        ally["气血"] = 0
        self.assertEqual(be.check_battle_end([actor, ally, enemy]), "敌方")
        enemy["气血"] = 0
        self.assertEqual(be.check_battle_end([actor, ally, enemy]), "敌方")


class AiCandidateTest(unittest.TestCase):
    def test_no_skill_or_item_returns_rest(self):
        actor = make_char()
        enemy = make_char("乙", "敌方")
        action = be.ai_decide(actor, [actor, enemy], be.load_skills(), {}, allow_escape=True)
        self.assertEqual(action, {"类型": "休息"})

    def test_attack_candidates_skip_ethereal_targets(self):
        actor = make_char()
        hidden = make_char("乙", "敌方")
        visible = make_char("丙", "敌方")
        sm.apply_status(hidden, "ethereal", 2)
        base = be.load_skills().get("太祖长拳")
        available = [(base, dict(base))]
        with patch.object(ai_styles, "_pick_weighted", return_value=0), \
                patch.object(ai_styles.skill_scorer, "score_skill", return_value=10), \
                patch.object(ai_styles.skill_scorer, "score_target", return_value=1), \
                patch.object(ai_styles.skill_scorer, "score_rest", return_value=0), \
                patch.object(ai_styles.skill_scorer, "score_surrender", return_value=0):
            action = ai_styles._pick_action(available, [], actor, [actor, hidden, visible],
                                            can_surrender=False)
        self.assertEqual(action["类型"], "武学")
        self.assertEqual(action["目标"], "丙")

    def test_player_side_ai_cannot_escape_or_surrender(self):
        player = make_char("玩家")
        teammate = make_char("队友")
        enemy = make_char("乙", "敌方")
        teammate["携带物品"] = ["小还丹"]
        teammate["物品"] = ["小还丹"]
        teammate["物品可用次数"] = {"小还丹": 1}
        chars_db = {"队友": {"名称": "队友", "战斗风格": "平衡", "携带武学": []}}
        style = Mock(return_value={"类型": "休息"})
        with patch.dict(be.ai_styles.STYLES, {"平衡": style}):
            be.ai_decide(teammate, [player, teammate, enemy], be.load_skills(), chars_db,
                         allow_escape=True, player_names=["玩家"])
        self.assertFalse(style.call_args.args[5])
        self.assertFalse(style.call_args.kwargs["can_surrender"])


if __name__ == "__main__":
    unittest.main()
