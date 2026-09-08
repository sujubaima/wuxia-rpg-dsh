#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一战斗钩子专项回归测试。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import battle_engine as be


def make_char(name, team="我方", hp=5000, mp=1500):
    attrs = {
        "气血上限": 5000, "内力上限": 2000,
        "攻击力": 150, "防御力": 120, "精准": 120, "识破": 120,
        "暴击": 80, "速度": 100,
        "力道": 30, "根骨": 30, "内功": 30, "身法": 30,
        "休息气血恢复": 0, "休息内力恢复": 0.1,
    }
    return {
        "名称": name, "阵营": team, "气血": hp, "内力": mp,
        "状态效果": [], "二级属性": attrs,
        "一级属性": {"力道": 30, "根骨": 30, "内功": 30, "身法": 30},
        "武艺": {"剑法": 10, "刀法": 10, "长兵": 10,
                 "奇门": 10, "暗器": 10, "搏击": 10},
        "冷却": {}, "充能": 0, "武学": [], "装备": {}, "物品": [],
    }


def make_skill(name="测试武学", effect=None, insight="无"):
    skill = {
        "名称": name, "类型": "剑法", "类别": "攻击", "目标范围": "敌方单体",
        "威力倍率": 1.0, "内力消耗": 0, "冷却时间": 0,
        "识破类型": insight, "等级增益": [], "_等级": 1,
    }
    if effect:
        skill["技能特效"] = effect
    return skill


def deterministic_roll(a, b):
    return 1.0 if b <= 1.05 else 99


class UnifiedDispatcherTest(unittest.TestCase):
    def test_action_effect_runs_before_grouped_statuses(self):
        calls = []
        action_mod = SimpleNamespace(on_action=lambda source, ctx: calls.append("技能"))
        status_mods = {
            "甲态": SimpleNamespace(on_action=lambda source, ctx: calls.append(
                f"{source['持有者']['名称']}:{source['层数']}")),
            "乙态": SimpleNamespace(on_action=lambda source, ctx: calls.append(
                f"{source['持有者']['名称']}:{source['层数']}")),
        }
        actor = make_char("甲")
        target = make_char("乙", "敌方")
        actor["状态效果"] = [{"id": "甲态", "剩余时间": 2},
                             {"id": "甲态", "剩余时间": 2}]
        target["状态效果"] = [{"id": "乙态", "剩余时间": 2}]
        source = {"类型": "技能特效", "持有者": actor, "数据": make_skill(),
                  "模块": action_mod, "id": "action", "名称": "测试"}
        ctx = be.make_combat_context(actor, source["数据"], {}, [actor, target],
                                     action_source=source)
        with patch.object(be.el, "load_effect", side_effect=lambda sid: status_mods.get(sid)):
            be.dispatch_combat_stage("on_action", ctx, source)
        self.assertEqual(calls, ["技能", "甲:2", "乙:1"])

    def test_stage_snapshot_defers_new_status(self):
        calls = []
        new_mod = SimpleNamespace(on_action=lambda source, ctx: calls.append("新状态"))

        def add_status(source, ctx):
            calls.append("技能")
            ctx["apply_status"](source["持有者"], "new_status", 2)

        actor = make_char("甲")
        skill = make_skill()
        source = {"类型": "技能特效", "持有者": actor, "数据": skill,
                  "模块": SimpleNamespace(on_action=add_status), "id": "action", "名称": "测试"}
        ctx = be.make_combat_context(actor, skill, {}, [actor], action_source=source)
        with patch.object(be.el, "load_effect", return_value=new_mod):
            be.dispatch_combat_stage("on_action", ctx, source)
            self.assertEqual(calls, ["技能"])
            be.dispatch_combat_stage("on_action", ctx)
        self.assertEqual(calls, ["技能", "新状态"])

    def test_failed_action_effect_does_not_gate_status(self):
        calls = []
        actor = make_char("甲")
        actor["状态效果"] = [{"id": "state", "剩余时间": 2}]
        source = {"类型": "技能特效", "持有者": actor, "数据": make_skill(),
                  "模块": SimpleNamespace(on_action=lambda source, ctx: calls.append("技能")),
                  "id": "action", "名称": "测试"}
        status_mod = SimpleNamespace(on_action=lambda source, ctx: calls.append("状态"))
        ctx = be.make_combat_context(actor, source["数据"], {}, [actor],
                                     action_source=source, effect_triggered=False)
        with patch.object(be.el, "load_effect", return_value=status_mod):
            be.dispatch_combat_stage("on_action", ctx, source)
        self.assertEqual(calls, ["状态"])

    def test_multi_source_list_results_append(self):
        actor = make_char("甲")
        target = make_char("乙", "敌方")
        target["状态效果"] = [{"id": "state", "剩余时间": 2}]
        action_mod = SimpleNamespace(
            on_target_confirmed=lambda source, ctx: [
                {"目标": "甲", "变化": 1, "原值": 0, "新值": 1}],
            on_target_resolved=lambda source, ctx: {
                "时序变化": [{"目标": "甲", "变化": 2}],
                "追击": [{"目标": "乙", "伤害": 10}],
            },
        )
        status_mod = SimpleNamespace(
            on_target_confirmed=lambda source, ctx: [
                {"目标": "乙", "变化": -1, "原值": 0, "新值": -1}],
            on_target_resolved=lambda source, ctx: {
                "时序变化": [{"目标": "乙", "变化": -2}],
                "追击": [{"目标": "甲", "伤害": 5}],
            },
        )
        skill = make_skill()
        source = {"类型": "技能特效", "持有者": actor, "数据": skill,
                  "模块": action_mod, "id": "action", "名称": "测试"}
        result = {}
        ctx = be.make_combat_context(actor, skill, result, [actor, target], target,
                                     action_source=source)
        with patch.object(be.el, "load_effect", return_value=status_mod):
            be.dispatch_combat_stage("on_target_confirmed", ctx, source)
            be.dispatch_combat_stage("on_target_resolved", ctx, source)
        self.assertEqual(len(result["时序变化"]), 4)
        self.assertEqual(len(result["追击"]), 2)
        self.assertEqual(result["时序变化"][1]["来源状态"], "state")


class TargetFlowTest(unittest.TestCase):
    def test_dodge_short_circuits_later_target_stages(self):
        calls = []
        mod = SimpleNamespace(**{
            hook: (lambda name: lambda source, ctx: calls.append(name))(hook)
            for hook in be.COMBAT_STAGES if hook != "on_action"
        })
        actor = make_char("甲")
        target = make_char("乙", "敌方")
        actor["二级属性"]["精准"] = 0
        target["二级属性"]["精准"] = 1000
        skill = make_skill(effect="probe")
        source = {"类型": "技能特效", "持有者": actor, "数据": skill,
                  "模块": mod, "id": "probe", "名称": "测试"}
        with patch.object(be.random, "uniform", return_value=0):
            result = be._attack_target(actor, skill, target, [actor, target],
                                       be.status_attr, {"类型": "无"}, source)
        self.assertTrue(result["闪避"])
        self.assertEqual(calls, ["on_target_check"])

    def test_independent_insight_roll_is_reused(self):
        seen = []

        def record(source, ctx):
            if ctx["阶段"] != "on_target_check":
                seen.append((ctx["阶段"], id(ctx["识破"]), ctx["识破"].get("掷骰")))

        mod = SimpleNamespace(**{hook: record for hook in be.COMBAT_STAGES if hook != "on_action"})
        actor = make_char("甲")
        target = make_char("乙", "敌方")
        skill = make_skill(effect="probe", insight="独立")
        source = {"类型": "技能特效", "持有者": actor, "数据": skill,
                  "模块": mod, "id": "probe", "名称": "测试"}
        with patch.object(be.random, "uniform", side_effect=[99, 10, 99, 1.0]):
            result = be._attack_target(actor, skill, target, [actor, target],
                                       be.status_attr, {"类型": "独立"}, source)
        self.assertTrue(result["特效发动"])
        self.assertEqual(result["特效掷骰"], 10)
        self.assertEqual(len({row[1] for row in seen}), 1)
        self.assertEqual({row[2] for row in seen}, {10})

    def test_insight_context_types(self):
        actor = make_char("甲")
        targets = [make_char("乙", "敌方"), make_char("丙", "敌方")]
        eff = be.status_attr
        self.assertEqual(be.resolve_insight_ctx(make_skill(insight="无"), actor, targets, eff),
                         {"类型": "无"})
        independent = make_skill(effect="probe", insight="独立")
        self.assertEqual(be.resolve_insight_ctx(independent, actor, targets, eff),
                         {"类型": "独立"})
        shared = make_skill(effect="probe", insight="全体")
        self_contest = make_skill(effect="probe", insight="自对抗")
        with patch.object(be.random, "uniform", side_effect=[20, 20]):
            all_ctx = be.resolve_insight_ctx(shared, actor, targets, eff)
            self_ctx = be.resolve_insight_ctx(self_contest, actor, targets, eff)
        self.assertEqual(all_ctx["类型"], "全体")
        self.assertTrue(all_ctx["发动"])
        self.assertEqual(self_ctx["类型"], "自对抗")
        self.assertTrue(self_ctx["发动"])

    def test_dagou_bati_applies_even_when_every_target_dodges(self):
        actor = make_char("甲")
        targets = [make_char("乙", "敌方"), make_char("丙", "敌方")]
        skill = be.resolve_skill(be.load_skills().get("打狗棒法"), 1)
        source = be.make_action_source(actor, skill)
        insight = {"类型": "全体", "发动率": 100, "掷骰": 1, "发动": True}
        top_result = {}
        be._fire_action_stage(actor, skill, top_result, [actor, *targets], insight, source)
        with patch.object(be.random, "uniform", return_value=0):
            results = [be._attack_target(actor, skill, t, [actor, *targets],
                                         be.status_attr, insight, source) for t in targets]
        self.assertTrue(all(row["闪避"] for row in results))
        self.assertEqual(sum(e["id"] == "bati" for e in actor["状态效果"]), 2)

    def test_ignore_dodge_and_miss_swing_use_target_check(self):
        actor = make_char("甲")
        target = make_char("乙", "敌方")
        actor["二级属性"]["精准"] = 0
        target["二级属性"]["精准"] = 1000
        skill = make_skill(effect="ignore_dodge")
        source = be.make_action_source(actor, skill)
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            hit = be._attack_target(actor, skill, target, [actor, target],
                                    be.status_attr, {"类型": "无"}, source)
        self.assertFalse(hit["闪避"])
        self.assertEqual(hit["闪避率"], 0)

        actor = make_char("甲")
        target = make_char("乙", "敌方")
        actor["二级属性"]["精准"] = target["二级属性"]["精准"] = 100
        actor["状态效果"] = [{"id": "miss_swing", "剩余时间": 2,
                               "施加者": target["名称"]}]
        with patch.object(be.random, "uniform", return_value=25):
            miss = be._attack_target(actor, make_skill(), target, [actor, target],
                                     be.status_attr, {"类型": "无"})
        self.assertTrue(miss["闪避"])
        self.assertEqual(miss["闪避率"], 35)

    def test_counter_and_gaoyuan_trigger_only_on_enemy_hit(self):
        attacker = make_char("甲", "我方")
        defender = make_char("乙", "敌方")
        defender["武学"] = [{"名称": "高远无极功", "等级": 10}]
        defender["状态效果"] = [
            {"id": "counter_attack", "剩余时间": 2},
            {"id": "gaoyuan_wuji", "剩余时间": 2},
        ]
        event = {"事件": "攻击命中", "攻击方": attacker, "目标": defender,
                 "武学": make_skill()}
        result = {}
        ctx = be.make_combat_context(attacker, event["武学"], result,
                                     [attacker, defender], defender, event)
        be.dispatch_combat_stage("on_target_confirmed", ctx)
        self.assertEqual(attacker["充能"], -50)
        self.assertEqual(defender["充能"], 150)
        self.assertEqual(len(result["时序变化"]), 3)

        ally = make_char("丙", "敌方")
        event = {"事件": "攻击命中", "攻击方": ally, "目标": defender,
                 "武学": make_skill()}
        ctx = be.make_combat_context(ally, event["武学"], {}, [ally, defender],
                                     defender, event)
        be.dispatch_combat_stage("on_target_confirmed", ctx)
        self.assertEqual(ally["充能"], 0)
        self.assertEqual(defender["充能"], 150)


class SpecialMechanicsTest(unittest.TestCase):
    def test_yinyang_redirects_before_actual_target_bati(self):
        actor = make_char("甲")
        original = make_char("弱", "敌方")
        actual = make_char("强", "敌方")
        be.apply_status(actual, "bati", 2)
        skill = be.resolve_skill(be.load_skills().get("阴阳错剑"), 1)
        source = be.make_action_source(actor, skill)
        event = {"事件": "伤害", "攻击方": actor, "目标": original,
                 "原目标": original, "落气血": 100, "落内力": 0,
                 "来源": skill["名称"]}
        ctx = be.make_combat_context(actor, skill, {}, [actor, original, actual],
                                     original, event, source)
        with patch.object(source["模块"].random, "choice", return_value=actual):
            be.settle([actor, original, actual], event, source, ctx)
        self.assertIs(event["目标"], actual)
        self.assertEqual(original["气血"], 5000)
        self.assertEqual(actual["气血"], 5000)
        self.assertFalse(any(e["id"] == "bati" for e in actual["状态效果"]))
        self.assertIn("霸体抵挡", event)

    def test_renyi_new_qiangming_protects_current_damage(self):
        actor = make_char("甲")
        skill = be.resolve_skill(be.load_skills().get("仁剑义剑"), 1)
        source = be.make_action_source(actor, skill)

        survivor = make_char("乙", "敌方")
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            result = be._attack_target(actor, skill, survivor, [actor, survivor],
                                       be.status_attr, {"类型": "无"}, source)
        self.assertGreater(survivor["气血"], 0)
        self.assertEqual({e["id"] for e in survivor["状态效果"]}, {"po_fang", "qiangming"})
        self.assertEqual(len(result["施加状态"]), 2)

        guarded = make_char("丙", "敌方", hp=1)
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            result = be._attack_target(actor, skill, guarded, [actor, guarded],
                                       be.status_attr, {"类型": "无"}, source)
        self.assertEqual(guarded["气血"], 1)
        self.assertEqual([e["id"] for e in guarded["状态效果"]], ["po_fang"])
        self.assertEqual(result["强命保命"][0]["名称"], "强命")

    def test_mohe_and_xizi_share_damage_calc_in_order(self):
        actor = make_char("甲", mp=300)
        target = make_char("乙", "敌方", mp=100)
        actor["状态效果"] = [
            {"id": "xizi_pengxin", "剩余时间": -1},
            {"id": "xinji", "剩余时间": -1},
        ]
        skill = be.resolve_skill(be.load_skills().get("摩诃无量指"), 1)
        source = be.make_action_source(actor, skill)
        event = {"事件": "伤害计算", "攻击方": actor, "目标": target,
                 "武学": skill, "伤害": 100, "增伤倍率": 1.0, "增伤来源": []}
        result = {}
        ctx = be.make_combat_context(actor, skill, result, [actor, target], target,
                                     event, source)
        be.dispatch_combat_stage("on_damage_calc", ctx, source)
        self.assertEqual(event["伤害"], 156)
        self.assertEqual(event["增伤倍率"], 1.2)
        self.assertEqual(actor["内力"], 100)
        self.assertEqual(result["无量之力差额"], 200)

    def test_splash_and_leiyin_followups_use_full_settlement(self):
        actor = make_char("甲")
        main = make_char("乙", "敌方")
        other = make_char("丙", "敌方")
        be.apply_status(other, "bati", 2)
        skill = be.resolve_skill(be.load_skills().get("霹雳棍法"), 1)
        source = be.make_action_source(actor, skill)
        with patch.object(be.random, "uniform", side_effect=deterministic_roll):
            result = be._attack_target(actor, skill, main, [actor, main, other],
                                       be.status_attr, {"类型": "无"}, source)
        self.assertEqual(result["追击结算"][0]["伤害"], 0)
        self.assertIn("霸体抵挡", result["追击结算"][0])
        self.assertFalse(any(e["id"] == "bati" for e in other["状态效果"]))

        target = make_char("丁", "敌方")
        target["状态效果"] = [
            {"id": "leiyin", "剩余时间": 10} for _ in range(4)
        ]
        skill = be.resolve_skill(be.load_skills().get("五雷天心掌"), 1)
        source = be.make_action_source(actor, skill)
        with patch.object(be.random, "uniform", side_effect=[99, 1, 99, 1.0]), \
                patch.object(source["模块"].random, "random", return_value=0):
            result = be._attack_target(actor, skill, target, [actor, target],
                                       be.status_attr, {"类型": "独立"}, source)
        self.assertIn("追击结算", result)
        self.assertFalse(any(e["id"] == "leiyin" for e in target["状态效果"]))

    def test_plain_and_scripted_items_keep_expected_flow(self):
        item = dict(be.load_items()["小还丹"])
        actor = make_char("甲", hp=100)
        target = make_char("乙", hp=100)
        actor["物品"] = ["小还丹"]
        actor["物品可用次数"] = {"小还丹": 1}
        ctx = be.make_combat_context(actor, item, {}, [actor, target], target)
        self.assertEqual(ctx["行动类型"], "物品")
        result = be.execute_action(actor, {"类型": "物品", "物品": item, "目标": "乙"},
                                   [actor, target])
        self.assertEqual(target["气血"], 500)
        self.assertEqual(actor["物品"], [])
        self.assertEqual(result["恢复气血"], 400)

        calls = []

        def hook(name):
            return lambda source, ctx: calls.append(
                (name, ctx["行动类型"], ctx["事件"].get("事件")))

        mod = SimpleNamespace(
            on_action=hook("action"), on_target_confirmed=hook("confirmed"),
            on_settle=hook("settle"), on_before_commit=hook("commit"),
            on_target_resolved=hook("resolved"),
        )
        actor = make_char("甲", hp=100)
        target = make_char("乙", hp=100)
        actor["物品"] = ["小还丹"]
        actor["物品可用次数"] = {"小还丹": 1}
        scripted = dict(item, 物品特效="probe")
        with patch.object(be.el, "load_item_effect", return_value=mod):
            be.execute_action(actor, {"类型": "物品", "物品": scripted, "目标": "乙"},
                              [actor, target])
        self.assertEqual(calls, [
            ("action", "物品", None), ("confirmed", "物品", "物品目标确认"),
            ("settle", "物品", "治疗"), ("commit", "物品", "治疗"),
            ("resolved", "物品", "目标结算"),
        ])

    def test_all_scripted_skills_load_and_run_real_insight_flow(self):
        skills = be.load_skills()
        scripted = [skills.get(name) for name in skills.names()
                    if skills.get(name) and skills.get(name).get("技能特效")]
        self.assertGreaterEqual(len(scripted), 60)
        checked = []
        for base in scripted:
            name = base["名称"]
            with self.subTest(skill=name):
                self.assertIn(base.get("识破类型"), be.INSIGHT_TYPES)
                actor = make_char("甲")
                target = make_char("乙", "敌方", hp=50000)
                other = make_char("丙", "敌方", hp=50000)
                actor["二级属性"]["精准"] = 1000
                actor["二级属性"]["识破"] = 1000
                target["二级属性"]["精准"] = 0
                target["二级属性"]["识破"] = 0
                other["二级属性"]["精准"] = 0
                other["二级属性"]["识破"] = 0
                skill = be.resolve_skill(base, 10)
                actor["武学"] = [{"名称": name, "等级": 10}]
                if skill.get("目标范围", "").startswith("我方") or skill.get("类别") == "治疗":
                    target = make_char("乙", "我方", hp=40000)
                characters = [actor, target, other]
                source = be.make_action_source(actor, skill)
                self.assertIsNotNone(source)
                self.assertEqual(source["id"], base["技能特效"])
                self.assertIsNotNone(source["模块"])
                self.assertTrue(any(callable(getattr(source["模块"], hook, None))
                                    for hook in be.COMBAT_STAGES))
                with patch.object(be.random, "uniform", side_effect=lambda a, b: 1.0):
                    insight = be.resolve_insight_ctx(skill, actor, [target, other], be.status_attr)
                    self.assertEqual(insight["类型"], base["识破类型"])
                    top = {}
                    be._fire_action_stage(actor, skill, top, characters, insight, source)
                    result = be._attack_target(actor, skill, target, characters,
                                               be.status_attr, insight, source)
                self.assertFalse(result.get("闪避", False))
                if base["识破类型"] != "无":
                    self.assertTrue(result["特效发动"])
                checked.append(name)
        self.assertEqual(len(checked), len(scripted))
        self.assertEqual(len(checked), len(set(checked)))


if __name__ == "__main__":
    unittest.main()
