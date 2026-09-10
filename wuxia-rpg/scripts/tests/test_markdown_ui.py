#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine 直出 Markdown 渲染层（settle/markdown_ui.py）与模式分支回归。

覆盖：20 个目标 UI 的模板、共享格式化、dsh/LLM/WEB_UI 模式分支、
go/judge 最终路径挂载，以及 GM 自检错误不渲染为玩家界面。
集成用例经隔离存档目录走真实 engine CLI。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)

from combat import battle
from common.render_mode import render_mode
from settle import engine_actions, title_flow
from settle.markdown_ui import (
    MARKDOWN_UI_IDS,
    RENDERERS,
    _effect_summary,
    _fmt_ts,
    _money,
    _pct,
    _txt,
    attach_render_text,
)


def with_env(mode):
    """构造渲染模式环境（mode=None 表示移除该变量）。"""
    env = dict(os.environ)
    env.pop("WUXIA_RPG_RENDER_MODULE", None)
    if mode is not None:
        env["WUXIA_RPG_RENDER_MODULE"] = mode
    return env


class HelperTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(_money(0), "0钱")
        self.assertEqual(_money(500), "500钱")
        self.assertEqual(_money(999), "999钱")
        self.assertEqual(_money(1000), "1两0钱")
        self.assertEqual(_money(1530), "1两530钱")
        self.assertEqual(_money(12345), "12两345钱")
        self.assertEqual(_money(None), "0钱")

    def test_pct(self):
        self.assertEqual(_pct(0.2), "20%")
        self.assertEqual(_pct(0.15), "15%")
        self.assertEqual(_pct(0), "0%")
        self.assertEqual(_pct(None), "—")

    def test_fmt_ts(self):
        self.assertEqual(_fmt_ts("20260910_140325"), "2026/09/10 14:03:25")
        self.assertEqual(_fmt_ts("bad"), "bad")
        self.assertEqual(_fmt_ts(None), "")

    def test_effect_summary(self):
        self.assertEqual(_effect_summary({"回复气血": 400}), "回复气血400")
        self.assertEqual(_effect_summary({"回复内力": 400}), "回复内力400")
        # 施加状态写持续回合（id 解析为状态名）
        self.assertEqual(_effect_summary({"施加状态": {"id": "huichun", "回合": 3, "层数": 2}}),
                         "施加回春（3回合）")
        self.assertEqual(_effect_summary({"施加状态": {"id": "dazzle", "回合": 2}}), "施加目盲（2回合）")
        self.assertEqual(_effect_summary({"施加状态": {"id": "unknown_x", "回合": 2}}), "施加unknown_x（2回合）")
        self.assertEqual(_effect_summary({"时序": -100}), "时序-100")
        self.assertEqual(_effect_summary({"时序": 50}), "时序+50")
        self.assertEqual(_effect_summary({"净化": 1}), "净化1")
        self.assertEqual(_effect_summary({"削减": 1}), "削减1")
        self.assertEqual(_effect_summary({"延长": 1}), "延长1")
        self.assertEqual(_effect_summary({"回复气血": 400, "回复体力": 20}), "回复气血400、回复体力20")
        self.assertEqual(_effect_summary(None), "—")
        self.assertEqual(_effect_summary({}), "—")


class ExplorationUiTest(unittest.TestCase):
    def setUp(self):
        self.resp = {
            "界面": "exploration-ui",
            "当前位置": "嵩山·大雄宝殿", "时段": "清晨", "时间": "第一年 一月一日 卯时六刻",
            "剩余": 4, "剧情描写": "晨钟悠悠。\\n\\n僧众做早课。",
            "结算": [
                {"ok": True, "变更": "体力-1"},
                {"ok": True, "msg": "无变更条目"},
                {"ok": True, "变更": "自动存档完成"},
            ],
            "场景要素": [
                {"主体": "大雄宝殿内", "描写": "香烟缭绕"},
                {"主体": "香客", "描写": "", "特殊指令": [{"名称": "交谈观察", "可用": True}]},
            ],
            "相邻出口": [{"方位": "北", "邻场景": "少林客堂"}, {"方位": "南", "邻场景": "少林寺山门"}],
            "体力": 82, "金钱": 1530,
            "队伍状态": [{"名称": "柳序", "气血": 400, "气血上限": 400, "内力": 466, "内力上限": 466}],
        }

    def test_full_template(self):
        with patch.dict(os.environ, with_env(None)):
            attach_render_text(self.resp)
        self.assertEqual(self.resp["渲染模式"], "LLM")
        self.assertEqual(self.resp["渲染文本"], "\n".join([
            "### 【嵩山·大雄宝殿】 清晨 第一年 一月一日 卯时六刻　距下次自动存档 4 轮",
            "",
            "晨钟悠悠。",
            "",
            "僧众做早课。",
            "",
            "`体力-1`",
            "`自动存档完成`",
            "",
            "周围情况",
            "- 大雄宝殿内（香烟缭绕）",
            "- 香客",
            "",
            "相邻出口",
            "- 北（通往少林客堂）",
            "- 南（通往少林寺山门）",
            "",
            "当前队伍　体力82　金钱1两530钱",
            "- `柳序` 气血(400/400) 内力(466/466)",
            "",
            "请输入指令（前往地点、与角色对话、观察场景、可通过`指令查询`了解全部指令）：",
        ]))

    def test_empty_exits_keeps_title(self):
        self.resp["相邻出口"] = []
        out = RENDERERS["exploration-ui"](self.resp)
        self.assertIn("\n相邻出口\n- （无）\n", out)


class ExplorationBattleUiTest(unittest.TestCase):
    def test_with_teammates(self):
        resp = {
            "界面": "exploration-battle-ui",
            "当前位置": "嵩山·山道", "时段": "傍晚", "时间": "第一年 一月三日 酉时六刻",
            "剩余": 2, "剧情描写": "刀光乍现。",
            "结算": [{"ok": True, "变更": "体力-2"}],
            "我方": ["沈孤鸿", "柳序"], "敌方": ["山贼甲", "山贼乙"],
            "主控": "沈孤鸿", "操控选项": ["玩家角色", "我方全员", "AI自动"],
        }
        self.assertEqual(RENDERERS["exploration-battle-ui"](resp), "\n".join([
            "### 【嵩山·山道】 傍晚 第一年 一月三日 酉时六刻　距下次自动存档 2 轮",
            "",
            "刀光乍现。",
            "",
            "`体力-2`",
            "",
            "战局双方",
            "我方：沈孤鸿、柳序",
            "敌方：山贼甲、山贼乙",
            "",
            "操控方式",
            "- 玩家角色：仅操控 沈孤鸿",
            "- 我方全员：操控我方所有角色",
            "- AI自动：我方全由 AI 操控，玩家观战至战斗结束",
            "",
            "请输入指令（选择操控方式、可通过`指令查询`了解全部指令）：",
        ]))

    def test_without_plot_and_teammates(self):
        resp = {
            "界面": "exploration-battle-ui",
            "当前位置": "嵩山·山道", "时段": "傍晚", "时间": "第一年 一月三日 酉时六刻",
            "剩余": 2, "我方": ["沈孤鸿"], "敌方": ["山贼甲"],
            "主控": "沈孤鸿", "操控选项": ["玩家角色", "AI自动"],
        }
        out = RENDERERS["exploration-battle-ui"](resp)
        self.assertNotIn("刀光", out)
        self.assertNotIn("我方全员", out)
        self.assertIn("- 玩家角色：仅操控 沈孤鸿", out)


class SaveUiTest(unittest.TestCase):
    def test_saves_with_fallback_progress(self):
        resp = {
            "界面": "save-ui", "槽位": 7,
            "存档列表": [{"slot": 7, "角色名": "柳序", "进度": "初入少林。",
                          "saves": [
                              {"序号": 1, "时间戳": "20260910_140325", "label": "自动存档"},
                              {"序号": 2, "时间戳": "20260901_090000", "label": ""},
                          ]}],
        }
        self.assertEqual(RENDERERS["save-ui"](resp), "\n".join([
            "【读档 · Slot_7 柳序】",
            "",
            "- File_1 2026/09/10 14:03:25 — 自动存档",
            "- File_2 2026/09/01 09:00:00 — 初入少林。",
            "",
            "请输入指令（选择存档、返回游历）：",
        ]))

    def test_empty_list(self):
        resp = {"界面": "save-ui", "槽位": 3, "存档列表": []}
        out = RENDERERS["save-ui"](resp)
        self.assertIn("当前角色尚无可读取存档", out)
        self.assertIn("【读档 · Slot_3】", out)


class WuxueUiTest(unittest.TestCase):
    def test_template(self):
        resp = {
            "界面": "wuxue-ui", "角色": "柳序",
            "结算": [{"ok": True, "变更": "装上 太乙玄门剑"}],
            "运转心法": None, "运转心法特效": "",
            "携带武学": [{"名称": "太乙玄门剑", "等级": 1, "类型": "剑法", "目标范围": "敌方单体",
                          "威力倍率": 0.85, "内力消耗": 64, "冷却时间": 0, "特效": ""}],
            "可用武学": [{"名称": "夜叉棍法", "等级": 2, "类型": "长兵", "目标范围": "敌方全体",
                          "威力倍率": 1.1, "内力消耗": 80, "冷却时间": 3, "特效": "命中后15%施加目盲"}],
        }
        self.assertEqual(RENDERERS["wuxue-ui"](resp), "\n".join([
            "### 【更换武学 · 柳序】",
            "",
            "`装上 太乙玄门剑`",
            "",
            "运转心法",
            "- `无`",
            "　特效：无",
            "",
            "携带武学（1/4）",
            "- `太乙玄门剑` Lv1（剑法 / 敌方单体 / 威力0.85 / 内力64 / 冷却无）",
            "　特效：无",
            "",
            "可用主动武学（已习得、未携带）",
            "- `夜叉棍法` Lv2（长兵 / 敌方全体 / 威力1.1 / 内力80 / 冷却3）",
            "　特效：命中后15%施加目盲",
            "",
            "请输入指令（运转心法、装上武学、卸下武学、替换武学、返回游历、可通过`指令查询`了解全部指令）：",
        ]))

    def test_empty_sections(self):
        resp = {"界面": "wuxue-ui", "角色": "柳序", "运转心法": None,
                "携带武学": [], "可用武学": []}
        out = RENDERERS["wuxue-ui"](resp)
        self.assertIn("携带武学（0/4）\n- （无）", out)
        self.assertIn("可用主动武学（已习得、未携带）\n- （无）", out)


class EquipUiTest(unittest.TestCase):
    def test_template_with_weapon_subtype(self):
        resp = {
            "界面": "equip-ui", "角色": "柳序",
            "结算": [{"ok": True, "变更": "卸下 长剑"}],
            "当前装备": {"武器1": "长剑", "武器2": None, "护甲": "布衣", "饰品": None, "冠巾": None},
            "可换装备": [{"名称": "铁剑", "类型": "武器", "子类型": "剑", "品级": 1, "品名": "上品"}],
        }
        self.assertEqual(RENDERERS["equip-ui"](resp), "\n".join([
            "### 【更换装备 · 柳序】",
            "",
            "`卸下 长剑`",
            "",
            "当前装备",
            "- 武器1：长剑（剑）",
            "- 武器2：空",
            "- 护甲：布衣",
            "- 饰品：空",
            "- 冠巾：空",
            "",
            "可换装备",
            "- `铁剑`（剑/上品）",
            "",
            "请输入指令（装备 [物品] [槽位]、卸下 [槽位]、返回游历、可通过`指令查询`了解全部指令）：",
        ]))

    def test_empty_available(self):
        resp = {"界面": "equip-ui", "角色": "柳序",
                "当前装备": {}, "可换装备": []}
        out = RENDERERS["equip-ui"](resp)
        self.assertIn("可换装备\n- （无）", out)
        self.assertIn("- 武器1：空", out)


class ItemUiTest(unittest.TestCase):
    def test_template(self):
        resp = {
            "界面": "item-ui", "角色": "柳序",
            "携带道具": [
                {"名称": "小还丹", "数量": 2, "子类型": "丹药", "使用效果": {"回复气血": 400}},
                {"名称": "回春散", "数量": 1, "子类型": "丹药",
                 "使用效果": {"施加状态": {"id": "huichun", "回合": 3, "层数": 2}}},
                {"名称": "爆竹", "数量": 1, "子类型": "道具", "使用效果": {"时序": -100}},
            ],
            "可换道具": [{"名称": "保和丸", "数量": 1, "子类型": "丹药", "使用效果": {"削减": 1}}],
        }
        self.assertEqual(RENDERERS["item-ui"](resp), "\n".join([
            "### 【更换道具 · 柳序】",
            "",
            "携带道具（3/4）",
            "- `小还丹`（丹药）×2",
            "　效果：回复气血400",
            "- `回春散`（丹药）×1",
            "　效果：施加回春（3回合）",
            "- `爆竹`（道具）×1",
            "　效果：时序-100",
            "",
            "可换道具",
            "- `保和丸`（丹药）×1",
            "　效果：削减1",
            "",
            "请输入指令（携带 [物品]、卸下 [物品]、替换 [新物品] [原物品]、返回游历、"
            "可通过`指令查询`了解全部指令）：",
        ]))

    def test_no_effect_shows_dash(self):
        resp = {"界面": "item-ui", "角色": "柳序", "携带道具": [{"名称": "怪药", "数量": 1, "子类型": "丹药"}],
                "可换道具": []}
        out = RENDERERS["item-ui"](resp)
        self.assertIn("　效果：—", out)
        self.assertIn("可换道具\n- （无）", out)


class MasteryUiTest(unittest.TestCase):
    def test_table_verbatim_with_settlement(self):
        resp = {"界面": "mastery-ui", "角色": "柳序",
                "结算": [{"ok": True, "变更": "百缠手 精进至第2境"}],
                "十境表": "【百缠手】十境表　品级0（精进消耗×1）\n……"}
        self.assertEqual(RENDERERS["mastery-ui"](resp), "\n".join([
            "### 【武学精进 · 柳序】",
            "",
            "`百缠手 精进至第2境`",
            "",
            "【百缠手】十境表　品级0（精进消耗×1）",
            "……",
            "",
            "请输入指令（精进下一境界、更换武学 [武学]、返回游历、可通过`指令查询`了解全部指令）：",
        ]))


class CharacterUiTest(unittest.TestCase):
    def test_template(self):
        resp = {
            "界面": "character-ui", "角色": "柳序",
            "角色信息": {
                "名称": "柳序", "性别": "男", "年龄": 20, "经验值": 102,
                "气血": 400, "气血上限": 430, "内力": 466, "内力上限": 466,
                "一级属性": {"内功": 6, "力道": 7, "身法": 6, "根骨": 5},
                "极性": {"阴阳": "阴", "刚柔": "刚", "动静": "中", "巧拙": "巧"},
                "武艺": {"搏击": 6, "剑法": 11, "刀法": 7, "长兵": 7, "奇门": 1, "暗器": 5},
                "技艺": {"音律": 5, "弈棋": 7, "诗书": 6, "绘画": 4, "医术": 4, "博物": 10},
                "二级属性": {"攻击力": 39, "防御力": 42, "速度": 47, "精准": 42, "识破": 40, "暴击": 50},
                "携带技能": ["太乙玄门剑"],
                "运转心法": None,
                "装备": {"武器1": "长剑", "武器2": None, "护甲": "布衣", "饰品": None, "冠巾": None},
                "携带物品": ["小还丹", "补气丸"],
                "死亡": False,
            },
        }
        self.assertEqual(RENDERERS["character-ui"](resp), "\n".join([
            "### 【人物 · 柳序】 男 20岁　经验：102",
            "",
            "| 内功/阴 | 力道/刚 | 身法/中 | 根骨/巧 |",
            "|------|------|------|------|",
            "| 6 | 7 | 6 | 5 |",
            "",
            "| 搏击 | 剑法 | 刀法 | 长兵 | 奇门 | 暗器 |",
            "|------|------|------|------|------|------|",
            "| 6 | 11 | 7 | 7 | 1 | 5 |",
            "",
            "| 音律 | 弈棋 | 诗书 | 绘画 | 医术 | 博物 |",
            "|------|------|------|------|------|------|",
            "| 5 | 7 | 6 | 4 | 4 | 10 |",
            "",
            "| 气血 | 内力 | 攻击力 | 防御力 | 速度 | 精准 | 识破 | 暴击 |",
            "|------|------|--------|--------|------|------|------|------|",
            "| 400/430 | 466/466 | 39 | 42 | 47 | 42 | 40 | 50 |",
            "",
            "运转心法：无",
            "携带武学：太乙玄门剑",
            "",
            "装备",
            "武器1：长剑　武器2：空",
            "护甲：布衣　饰品：空　冠巾：空",
            "携带物品：小还丹、补气丸",
            "",
            "请输入指令（查看其他角色 [名称]、返回游历、可通过`指令查询`了解全部指令）：",
        ]))

    def test_dead_mark_and_empty_lists(self):
        info = {"名称": "甲", "性别": "女", "年龄": 30, "经验值": 0,
                "一级属性": {}, "极性": {}, "武艺": {}, "技艺": {}, "二级属性": {},
                "携带技能": [], "运转心法": None, "装备": {}, "携带物品": [], "死亡": True}
        out = RENDERERS["character-ui"]({"界面": "character-ui", "角色信息": info})
        self.assertIn("携带物品：无（已殁）", out)
        self.assertIn("| 内功 | 力道 | 身法 | 根骨 |", out)


class BagUiTest(unittest.TestCase):
    def test_filter_text_and_table(self):
        resp = {
            "界面": "bag-ui", "角色": "柳序",
            "筛选": {"类型": ["武器", "消耗品"], "子类型": None, "适用场合": "世界"},
            "物品列表": [
                {"名称": "长剑", "数量": 1, "类型": "武器", "子类型": "剑", "品级": 1, "品名": "上品", "适用场合": "通用"},
                {"名称": "小还丹", "数量": 2, "类型": "消耗品", "子类型": "丹药", "品级": 1, "品名": "上品", "适用场合": "通用"},
            ],
        }
        self.assertEqual(RENDERERS["bag-ui"](resp), "\n".join([
            "### 【背包 · 柳序】",
            "筛选：类型 = 武器、消耗品　适用场合 = 世界",
            "",
            "| 物品 | 数量 | 类型 | 子类型 | 品级 | 适用场合 |",
            "|------|------|------|--------|------|----------|",
            "| `长剑` | ×1 | 武器 | 剑 | 上品 | 通用 |",
            "| `小还丹` | ×2 | 消耗品 | 丹药 | 上品 | 通用 |",
            "",
            "请输入指令（使用 [物品]、筛选 [类型/子类型/适用场合]、返回游历、可通过`指令查询`了解全部指令）：",
        ]))

    def test_all_filter_and_empty_bag(self):
        resp = {"界面": "bag-ui", "角色": "柳序", "筛选": {}, "物品列表": []}
        out = RENDERERS["bag-ui"](resp)
        self.assertIn("筛选：全部", out)
        self.assertIn("物品栏空空如也", out)
        self.assertNotIn("| 物品 |", out)


class TravelUiTest(unittest.TestCase):
    def test_routes_and_money_format(self):
        resp = {"界面": "travel-ui", "当前区域": "嵩山", "驿站类型": "山驿",
                "路线": [{"目的地": "洛阳", "耗时": 2, "费用": 240},
                         {"目的地": "开封", "耗时": 10, "费用": 1200}]}
        self.assertEqual(RENDERERS["travel-ui"](resp), "\n".join([
            "### 【驿站 · 嵩山】山驿",
            "",
            "可往：",
            "- `洛阳`　2天　240钱",
            "- `开封`　10天　1两200钱",
            "",
            "请输入指令（前往 [目的地]、返回游历、可通过`指令查询`了解全部指令）：",
        ]))

    def test_empty_routes(self):
        resp = {"界面": "travel-ui", "当前区域": "嵩山", "驿站类型": "山驿", "路线": []}
        out = RENDERERS["travel-ui"](resp)
        self.assertIn("此驿站暂无直达路线，需经他处换乘", out)


class InnUiTest(unittest.TestCase):
    def test_tiers(self):
        resp = {"界面": "inn-ui", "场景": "悦来客栈", "金钱": 1200,
                "等级": [
                    {"等级": "简朴", "每刻单价": 4, "体力每时辰": 15, "气血内力比例": 0.15, "时长": 32},
                    {"等级": "中等", "每刻单价": 5, "体力每时辰": 20, "气血内力比例": 0.2, "时长": 32},
                    {"等级": "奢华", "每刻单价": 6, "体力每时辰": 25, "气血内力比例": 0.25, "时长": 32},
                ]}
        self.assertEqual(RENDERERS["inn-ui"](resp), "\n".join([
            "### 【客栈 · 悦来客栈】　金钱 1两200钱",
            "",
            "固定休息4时辰（32刻）",
            "",
            "| 等级 | 每刻单价 | 总费用 | 体力/时辰 | 气血内力/时辰 |",
            "|------|------|------|------|------|",
            "| `简朴` | 4钱 | 128钱 | 15 | 上限15% |",
            "| `中等` | 5钱 | 160钱 | 20 | 上限20% |",
            "| `奢华` | 6钱 | 192钱 | 25 | 上限25% |",
            "",
            "请输入指令（休息 [等级]、返回游历、可通过`指令查询`了解全部指令）：",
        ]))


class WuxueListUiTest(unittest.TestCase):
    def test_active_and_xinfa(self):
        resp = {
            "界面": "wuxue-list-ui", "角色": "柳序",
            "主动武学": [{"名称": "太乙玄门剑", "等级": 1, "类型": "剑法", "品名": "凡品",
                          "威力倍率": 0.85, "内力消耗": 64, "冷却时间": 0, "特效": ""}],
            "心法": [{"名称": "纯阳无极功", "等级": 3, "品名": "上品", "特效": "运转时攻击+5"}],
        }
        self.assertEqual(RENDERERS["wuxue-list-ui"](resp), "\n".join([
            "### 【武学 · 柳序】",
            "",
            "主动武学",
            "- `太乙玄门剑` Lv1（剑法 / 凡品 / 威力0.85 / 内力64 / 冷却无）",
            "　特效：无",
            "",
            "心法",
            "- `纯阳无极功` Lv3（上品）",
            "　特效：运转时攻击+5",
            "",
            "请输入指令（查看其他角色 [名称]、查看武学详情 [武学]、返回游历、"
            "可通过`指令查询`了解全部指令）：",
        ]))

    def test_empty_sections(self):
        resp = {"界面": "wuxue-list-ui", "角色": "柳序", "主动武学": [], "心法": []}
        out = RENDERERS["wuxue-list-ui"](resp)
        self.assertIn("主动武学\n（无）", out)
        self.assertIn("心法\n（无）", out)


class TradeUiTest(unittest.TestCase):
    def test_buy_merchant_and_empty(self):
        resp = {"界面": "trade-buy-ui", "卖家": "张掌柜", "商人": True, "金钱": 2000,
                "货架": [{"名称": "小还丹", "数量": 3, "价格": 200, "类型": "消耗品",
                          "子类型": "丹药", "品名": "上品"}]}
        self.assertEqual(RENDERERS["trade-buy-ui"](resp), "\n".join([
            "### 【购买 · 张掌柜】（商人）　金钱 2两0钱",
            "",
            "| 物品 | 数量 | 单价 | 类型 | 子类型 | 品级 |",
            "|------|------|------|------|--------|------|",
            "| `小还丹` | ×3 | 200钱 | 消耗品 | 丹药 | 上品 |",
            "",
            "请输入指令（购买 [物品] [数量]、返回游历、可通过`指令查询`了解全部指令）：",
        ]))
        empty = {"界面": "trade-buy-ui", "卖家": "李猎户", "商人": False, "金钱": 0, "货架": []}
        out = RENDERERS["trade-buy-ui"](empty)
        self.assertIn("李猎户暂无可售物品", out)
        self.assertNotIn("（商人）", out)

    def test_sell(self):
        resp = {"界面": "trade-sell-ui", "买家": "王铁匠", "商人": False, "金钱": 500,
                "可售物品": [{"名称": "铁剑", "数量": 1, "价格": 300, "类型": "武器",
                              "子类型": "剑", "品名": "凡品"}]}
        self.assertEqual(RENDERERS["trade-sell-ui"](resp), "\n".join([
            "### 【出售 · 收购方 王铁匠】　金钱 500钱",
            "",
            "| 物品 | 数量 | 单价 | 类型 | 子类型 | 品级 |",
            "|------|------|------|------|--------|------|",
            "| `铁剑` | ×1 | 300钱 | 武器 | 剑 | 凡品 |",
            "",
            "请输入指令（出售 [物品] [数量]、返回游历、可通过`指令查询`了解全部指令）：",
        ]))
        empty = {"界面": "trade-sell-ui", "买家": "王铁匠", "商人": False, "金钱": 0, "可售物品": []}
        out = RENDERERS["trade-sell-ui"](empty)
        self.assertIn("物品栏空空如也", out)


class MessageUiTest(unittest.TestCase):
    def test_hint_verbatim(self):
        resp = {"界面": "message-ui", "提示": "此处不通。"}
        self.assertEqual(RENDERERS["message-ui"](resp), "✗ 此处不通。\n\n请重新输入指令：")

    def test_missing_hint_default(self):
        resp = {"界面": "message-ui"}
        out = RENDERERS["message-ui"](resp)
        self.assertTrue(out.startswith("✗ 指令不合法或信息不足"))


class MapUiTest(unittest.TestCase):
    def test_template(self):
        resp = {
            "界面": "map-ui", "当前区域": "嵩山", "当前场景": "大雄宝殿",
            "邻接图": "【大雄宝殿】\n├─ 北→ 少林客堂",
            "驿站出口": "嵩山山驿", "驿站类型": "山驿",
            "已知地点": [
                {"名称": "大雄宝殿", "标记": ["当前"]},
                {"名称": "少林客堂", "标记": None},
                {"名称": "嵩山山驿", "标记": ["驿站"]},
            ],
        }
        self.assertEqual(RENDERERS["map-ui"](resp), "\n".join([
            "### 【嵩山 · 场景地图】 当前：大雄宝殿",
            "",
            "```text",
            "【大雄宝殿】",
            "├─ 北→ 少林客堂",
            "```",
            "",
            "（出城：`嵩山山驿`，山驿）",
            "",
            "已知地点：`大雄宝殿`（当前）、`少林客堂`、`嵩山山驿`（出城）",
            "",
            "请输入指令（前往地点、返回游历、可通过`指令查询`了解全部指令）：",
        ]))

    def test_no_station_exit(self):
        resp = {"界面": "map-ui", "当前区域": "嵩山", "当前场景": "大雄宝殿",
                "邻接图": "【大雄宝殿】", "已知地点": []}
        out = RENDERERS["map-ui"](resp)
        self.assertNotIn("出城", out)
        self.assertIn("已知地点：（无）", out)


class BattleUiTest(unittest.TestCase):
    def test_battle_sections(self):
        cases = [
            ({"战报": "第一回合", "玩家界面": "### 玩家回合"},
             "第一回合\n\n### 玩家回合"),
            ({"战报": "第一回合"}, "第一回合"),
            ({"玩家界面": "### 玩家回合"}, "### 玩家回合"),
            ({}, ""),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                self.assertEqual(RENDERERS["battle-ui"]({"界面": "battle-ui", **fields}), expected)

    def test_battle_end_candidates_are_deterministic(self):
        resp = {
            "界面": "battle-end-ui",
            "战报": "终局战报",
            "处决候选": [
                {"名称": "甲", "状态": "败阵"},
                {"名称": "乙", "状态": "存活"},
                {"名称": "丙", "状态": "认输"},
                {"名称": "丁", "状态": "未知"},
            ],
        }
        self.assertEqual(RENDERERS["battle-end-ui"](resp), "\n".join([
            "终局战报",
            "",
            "### 【处决裁定】",
            "",
            "胜方处置败方，逐人决定：",
            "- 甲（倒地受制，气息尚存）",
            "- 乙（弃械受制，气息尚存）",
            "- 丙（俯首受制，气息尚存）",
            "- 丁（已被制住，气息尚存）",
            "",
            "请逐人答复（杀 / 放，可补充处置细节）：",
        ]))

    def test_battle_end_without_candidates(self):
        self.assertEqual(RENDERERS["battle-end-ui"]({"界面": "battle-end-ui"}), "\n".join([
            "### 【处决裁定】",
            "",
            "敌方均已逃走，无可处决之人。",
            "",
            "请输入指令（结束战斗）：",
        ]))


class BattlePayloadModeTest(unittest.TestCase):
    STATE = {
        "角色列表": [
            {"名称": "甲", "阵营": "我方"},
            {"名称": "乙", "阵营": "敌方"},
        ],
        "回合数": 1,
    }

    def _emit(self, mode):
        with patch.dict(os.environ, with_env(mode)), patch("builtins.print") as output:
            battle.emit_battle_json(
                self.STATE, "规范战报", player_ui="玩家面板", my_side="我方",
                回合详情=[{"回合": 1}], 行动信息={"行动者": "甲"})
        return json.loads(output.call_args.args[0])

    def test_llm_emits_text_only(self):
        payload = self._emit("LLM")
        self.assertEqual(payload["战报"], "规范战报")
        self.assertEqual(payload["玩家界面"], "玩家面板")
        self.assertNotIn("回合详情", payload)
        self.assertNotIn("行动信息", payload)

    def test_web_ui_emits_text_and_structure(self):
        payload = self._emit("WEB_UI")
        self.assertEqual(payload["战报"], "规范战报")
        self.assertEqual(payload["玩家界面"], "玩家面板")
        self.assertEqual(payload["回合详情"], [{"回合": 1}])
        self.assertEqual(payload["行动信息"], {"行动者": "甲"})

    def test_dsh_emits_structure_only(self):
        payload = self._emit("DSH")
        self.assertNotIn("战报", payload)
        self.assertNotIn("玩家界面", payload)
        self.assertEqual(payload["回合详情"], [{"回合": 1}])
        self.assertEqual(payload["行动信息"], {"行动者": "甲"})


class BattleAdvanceContractTest(unittest.TestCase):
    def test_cached_engine_report_is_preserved(self):
        cached = {"战报": "引擎规范战报", "战局状态": {"状态": "进行中"}}
        details = [{"回合": 1}]
        with patch.object(engine_actions, "_read_battle_last", return_value=cached):
            results, response = engine_actions._act_battle_advance(
                1, {}, {"类型": "战斗-推进", "回合详情": details})
        self.assertEqual(results, [])
        self.assertEqual(response["战报"], "引擎规范战报")
        self.assertEqual(response["回合详情"], details)
        self.assertEqual(response["界面"], "battle-ui")

    def test_obsolete_report_override_is_rejected_before_read(self):
        with patch.object(engine_actions, "_read_battle_last") as read_last:
            results = engine_actions._act_battle_advance(
                1, {}, {"类型": "战斗-推进", "战报文本": "GM 改写"})
        read_last.assert_not_called()
        self.assertFalse(results[0]["ok"])
        self.assertIn("不再接受 战报文本", results[0]["msg"])


class ClueUiTest(unittest.TestCase):
    def test_groups_and_rewards(self):
        resp = {
            "界面": "clue-ui",
            "进行中": [{"名称": "少林失经", "进展节点": [
                {"描述": "知客僧提起近日藏经阁失窃。", "奖励": ""},
                {"描述": "在后山发现陌生脚印。", "奖励": "经验+50"},
            ]}],
            "已关闭": [{"名称": "山道劫案", "进展节点": [
                {"描述": "击退劫匪。", "奖励": ""},
            ]}],
        }
        self.assertEqual(RENDERERS["clue-ui"](resp), "\n".join([
            "### 【线索栏】",
            "",
            "—— 进行中 ——",
            "`少林失经`",
            "1. 知客僧提起近日藏经阁失窃。",
            "2. 在后山发现陌生脚印。（经验+50）",
            "",
            "—— 已关闭 ——",
            "`山道劫案`　已了结",
            "1. 击退劫匪。",
            "",
            "请输入指令（返回游历、可通过`指令查询`了解全部指令）：",
        ]))

    def test_omit_empty_group_and_both_empty(self):
        resp = {"界面": "clue-ui", "进行中": [], "已关闭": [{"名称": "旧案", "进展节点": []}]}
        out = RENDERERS["clue-ui"](resp)
        self.assertNotIn("进行中", out)
        self.assertIn("`旧案`　已了结", out)
        both = RENDERERS["clue-ui"]({"界面": "clue-ui", "进行中": [], "已关闭": []})
        self.assertIn("尚无线索", both)


class TitleUiTest(unittest.TestCase):
    def test_homepage_and_read_browser(self):
        home = RENDERERS["title-ui"]({
            "界面": "title-ui", "标题状态": "主页", "版本": "0.9.8", "存档列表": [{"slot": 1}],
        })
        self.assertIn("── 武 侠 R P G ──", home)
        self.assertIn("版本：v0.9.8", home)
        self.assertIn("存档：1个", home)
        self.assertTrue(home.endswith("请输入指令（创建角色、读取存档）："))

        browser = RENDERERS["title-ui"]({
            "界面": "title-ui", "标题状态": "读档", "存档列表": [{
                "slot": 2, "角色名": "沈听雪", "进度": "旧事",
                "saves": [{"序号": 3, "时间戳": "20260910_140325", "label": "山雨欲来"}],
            }],
        })
        self.assertIn("【Slot_2 沈听雪】", browser)
        self.assertIn("File_3 2026/09/10 14:03:25 — 山雨欲来", browser)

    def test_creation_steps_and_validation_hint(self):
        draft = title_flow.fresh_draft()
        draft.update({"名称": "沈听雪", "性别": "女", "年龄": 18})
        stats = RENDERERS["title-ui"]({
            "界面": "title-ui", "标题状态": "创建-资质", "创建草稿": draft,
            "剩余点数": {"一级属性": 0, "武艺": 0, "技艺": 0},
            "校验提示": "点数不合法",
        })
        self.assertIn("第二步 · 分配资质", stats)
        self.assertIn("沈听雪（女）18岁", stats)
        self.assertIn("基础属性　剩余0点", stats)
        self.assertIn("✗ 点数不合法", stats)

        skills = RENDERERS["title-ui"]({
            "界面": "title-ui", "标题状态": "创建-武学", "创建草稿": draft,
            "初始武学列表": title_flow.starter_list(),
        })
        self.assertIn("武当派《太乙玄门剑》，配【长剑】", skills)
        self.assertIn("峨眉派《分水刺》，配【峨眉刺】", skills)

    def test_skill_detail_lists_all_ten_levels(self):
        draft = title_flow.fresh_draft()
        draft.update({"名称": "沈听雪", "性别": "女", "年龄": 18})
        detail = RENDERERS["title-ui"]({
            "界面": "title-ui", "标题状态": "创建-武学详情", "创建草稿": draft,
            "武学详情": title_flow.starter_detail("太乙玄门剑"),
        })
        self.assertIn("### 《太乙玄门剑》武当派 · 剑法", detail)
        self.assertIn("| Lv1 | — |", detail)
        self.assertIn("| Lv10 | 武艺剑法+2、威力倍率+15% |", detail)

    def test_stateless_actions_validate_and_randomize(self):
        with patch.object(title_flow.sm, "list_all_saves", return_value=[]), \
                patch.object(title_flow.sm, "next_slot_number", return_value=1):
            bad = title_flow.handle_title_action({
                "操作": "提交立名", "名称": "沈听雪", "性别": "女", "年龄": 15,
            })
            self.assertEqual(bad["标题状态"], "创建-立名")
            self.assertIn("16～80", bad["校验提示"])

            draft = title_flow.fresh_draft()
            draft.update({"名称": "沈听雪", "性别": "女", "年龄": 18})
            randomized = title_flow.handle_title_action({
                "操作": "随机分配", "创建草稿": draft,
            })["创建草稿"]
            for group, keys, total in title_flow.GROUPS:
                self.assertEqual(sum(randomized[group][key] for key in keys), total)
                self.assertTrue(all(0 <= randomized[group][key] <= title_flow.CAP for key in keys))


class AttachRenderTextTest(unittest.TestCase):
    SAMPLE = {"界面": "exploration-ui", "当前位置": "嵩山·大雄宝殿", "时段": "清晨",
              "时间": "第一年 一月一日 卯时六刻", "剩余": 4, "剧情描写": "晨钟悠悠。",
              "队伍状态": [], "体力": 82, "金钱": 500, "相邻出口": []}

    def test_all_twenty_markdown_ids_covered(self):
        self.assertEqual(len(MARKDOWN_UI_IDS), 20)
        self.assertEqual(set(RENDERERS), set(MARKDOWN_UI_IDS))
        self.assertIn("title-ui", MARKDOWN_UI_IDS)

    def test_dsh_returns_empty_string_for_all(self):
        for ui in MARKDOWN_UI_IDS:
            with self.subTest(ui=ui), patch.dict(os.environ, with_env("dsh")):
                resp = {"界面": ui, "提示": "x", "结算": []}
                attach_render_text(resp)
                self.assertEqual(resp["渲染文本"], "")
                self.assertEqual(resp["渲染模式"], "dsh")

    def test_dsh_case_insensitive(self):
        with patch.dict(os.environ, with_env("DSH")):
            resp = {"界面": "message-ui", "提示": "x"}
            attach_render_text(resp)
            self.assertEqual(resp["渲染文本"], "")

    def test_non_dsh_modes_render_markdown(self):
        for mode in (None, "LLM", "WEB_UI"):
            with self.subTest(mode=mode), patch.dict(os.environ, with_env(mode)):
                resp = dict(self.SAMPLE)
                attach_render_text(resp)
                expected_mode = mode if mode else "LLM"
                self.assertEqual(resp["渲染模式"], expected_mode)
                self.assertTrue(resp["渲染文本"].startswith("### 【嵩山·大雄宝殿】"))
                self.assertIn("请输入指令（", resp["渲染文本"])

    def test_title_ui_renders(self):
        with patch.dict(os.environ, with_env(None)):
            resp = {"界面": "title-ui", "标题状态": "主页", "版本": "0.9.8", "存档列表": []}
            attach_render_text(resp)
            self.assertEqual(resp["渲染模式"], "LLM")
            self.assertIn("武 侠 R P G", resp["渲染文本"])

    def test_missing_ui_untouched(self):
        with patch.dict(os.environ, with_env(None)):
            resp = {"结算": []}
            attach_render_text(resp)
            self.assertNotIn("渲染文本", resp)

    def test_gm_error_exploration_not_rendered(self):
        with patch.dict(os.environ, with_env(None)):
            resp = dict(self.SAMPLE, 错误="judge 状态变更结算异常：xxx")
            attach_render_text(resp)
            self.assertNotIn("渲染文本", resp)
            self.assertEqual(resp["渲染模式"], "LLM")

    def test_message_ui_with_error_renders(self):
        with patch.dict(os.environ, with_env(None)):
            resp = {"界面": "message-ui", "提示": "此处不通。"}
            attach_render_text(resp)
            self.assertEqual(resp["渲染文本"], "✗ 此处不通。\n\n请重新输入指令：")


# ----------------------------- 集成（真实 engine CLI） -----------------------------

ENGINE = os.path.join(SCRIPTS, "engine.py")

CHAR = {
    "名称": "沈孤鸿", "性别": "男", "年龄": 20, "人设": "沉默寡言的独行客",
    "一级属性": {"内功": 6, "力道": 6, "身法": 6, "根骨": 6},
    "武艺": {"搏击": 1, "剑法": 8, "刀法": 1, "长兵": 1, "奇门": 1, "暗器": 1},
    "技艺": {"音律": 1, "弈棋": 1, "诗书": 1, "绘画": 1, "医术": 1, "博物": 1},
    "极性": {"阴阳": "中", "刚柔": "中", "动静": "中", "巧拙": "中"},
    "武学": [{"名称": "太乙玄门剑", "等级": 1}], "运转心法": None, "携带技能": ["太乙玄门剑"],
    "装备": {"武器1": "长剑", "护甲": "布衣"},
    "物品": ["小还丹", "小还丹", "补气丸"],
}


def run_engine(slot, payload, cmd, save_dir, mode=None):
    env = dict(os.environ, WUXIA_RPG_SAVE_DIR=save_dir)
    env.pop("WUXIA_RPG_RENDER_MODULE", None)
    if mode is not None:
        env["WUXIA_RPG_RENDER_MODULE"] = mode
    proc = subprocess.run(
        [sys.executable, ENGINE, cmd],
        input=json.dumps({"槽位": slot, **payload}, ensure_ascii=False),
        capture_output=True, text=True, env=env, cwd=SCRIPTS)
    if proc.returncode != 0:
        raise AssertionError(f"engine {cmd} 失败：{proc.stderr}")
    return json.loads(proc.stdout)


class EngineIntegrationTest(unittest.TestCase):
    """经真实 engine CLI 验证 go/judge 三条最终路径都挂载 渲染文本。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.save_dir = os.path.join(cls._tmp.name, "save")
        title = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, "go", cls.save_dir)
        cls.slot = title["next_slot"]
        created = run_engine(cls.slot, {"行为": [{"类型": "创建角色", "角色": CHAR}]}, "go", cls.save_dir)
        assert not created.get("错误"), created.get("错误")
        # 开场 judge：落点为驿站功能场景，要素须含功能NPC+特殊指令
        cls.opening = run_engine(cls.slot, {
            "行为": [], "当前剧情": "沈孤鸿初入江湖。",
            "场景要素": [
                {"主体": "海风", "描写": "咸腥扑面"},
                {"主体": "驿丞", "描写": "案后整理文书",
                 "特殊指令": [{"名称": "远行（舟车）", "可用": True}]},
            ]}, "judge", cls.save_dir)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _start_battle(self):
        title = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, "go", self.save_dir)
        slot = title["next_slot"]
        created = run_engine(slot, {"行为": [{"类型": "创建角色", "角色": CHAR}]}, "go", self.save_dir)
        self.assertFalse(created.get("错误"))
        opening = run_engine(slot, {
            "行为": [], "当前剧情": "沈孤鸿初入江湖。",
            "场景要素": [
                {"主体": "海风", "描写": "咸腥扑面"},
                {"主体": "驿丞", "描写": "案后整理文书",
                 "特殊指令": [{"名称": "远行（舟车）", "可用": True}]},
            ]}, "judge", self.save_dir)
        self.assertFalse(opening.get("错误"))
        # 隔离用例中增强主控，确保开战自动推进稳定停在玩家回合，不受随机先手影响。
        char_path = os.path.join(self.save_dir, f"slot_{slot}", ".data", "characters", "散人", "沈孤鸿.json")
        with open(char_path, "r", encoding="utf-8") as file:
            player = json.load(file)
        player["一级属性"] = {"内功": 1000, "力道": 1000, "身法": 1000, "根骨": 1000}
        with open(char_path, "w", encoding="utf-8") as file:
            json.dump(player, file, ensure_ascii=False, indent=2)
        attack = run_engine(slot, {"行为": [{"类型": "攻击", "目标": "路不平"}]},
                            "go", self.save_dir)
        self.assertFalse(attack.get("错误"))
        triggered = run_engine(slot, {
            "行为": [{"类型": "战斗-触发", "我方": ["沈孤鸿"],
                    "敌方": ["路不平"], "允许逃跑": True}],
            "当前剧情": "路不平拦路！"}, "judge", self.save_dir)
        self.assertEqual(triggered.get("界面"), "exploration-battle-ui")
        started = run_engine(slot, {
            "行为": [{"类型": "战斗-开始", "我方": ["沈孤鸿"], "敌方": ["路不平"],
                    "允许逃跑": True, "操控方式": "玩家角色"}],
            "当前剧情": "路不平拦路！"}, "judge", self.save_dir)
        self.assertFalse(started.get("错误"))
        return slot, started

    def _rewrite_battle_hp(self, slot, player_hp, enemy_hp):
        path = os.path.join(self.save_dir, f"slot_{slot}", ".runtime", "battle", "battle_state.json")
        with open(path, "r", encoding="utf-8") as file:
            state = json.load(file)
        for character in state["角色列表"]:
            hp = player_hp if character["名称"] == "沈孤鸿" else enemy_hp
            character["气血"] = hp
            character["气血上限"] = max(character.get("气血上限", 0), hp)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)

    def test_judge_exploration_attaches_markdown(self):
        self.assertEqual(self.opening.get("界面"), "exploration-ui")
        self.assertIsNone(self.opening.get("错误"))
        self.assertEqual(self.opening.get("渲染模式"), "LLM")
        text = self.opening.get("渲染文本")
        self.assertTrue(text and text.startswith("### 【"))
        self.assertIn("沈孤鸿初入江湖。", text)
        self.assertIn("`角色已创建`", text)
        self.assertIn("请输入指令（", text)

    def test_go_panel_and_exploration_attach(self):
        bag = run_engine(self.slot, {"行为": [{"类型": "查看背包"}]}, "go", self.save_dir)
        self.assertEqual(bag.get("界面"), "bag-ui")
        self.assertTrue(bag["渲染文本"].startswith("### 【背包 · 沈孤鸿】"))
        back = run_engine(self.slot, {"行为": [{"类型": "返回游戏"}]}, "go", self.save_dir)
        self.assertEqual(back.get("界面"), "exploration-ui")
        self.assertTrue(back["渲染文本"].startswith("### 【"))

    def test_judge_battle_trigger_attaches_markdown(self):
        # 战斗-触发后槽位进入 AWAITING_BATTLE_START，会污染共享槽位的回合状态，
        # 故另建独立 slot 验证（不与其它用例共状态）。
        title = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, "go", self.save_dir)
        slot = title["next_slot"]
        created = run_engine(slot, {"行为": [{"类型": "创建角色", "角色": CHAR}]}, "go", self.save_dir)
        self.assertFalse(created.get("错误"))
        run_engine(slot, {"行为": [{"类型": "交谈观察"}]}, "go", self.save_dir)
        bt = run_engine(slot, {
            "行为": [{"类型": "战斗-触发", "我方": ["沈孤鸿"], "敌方": ["山贼甲"], "允许逃跑": True}],
            "当前剧情": "夜色中刀光乍现。"}, "judge", self.save_dir)
        self.assertEqual(bt.get("界面"), "exploration-battle-ui")
        text = bt.get("渲染文本")
        self.assertTrue(text)
        self.assertIn("战局双方", text)
        self.assertIn("我方：沈孤鸿", text)
        self.assertIn("操控方式", text)
        self.assertIn("- 玩家角色：仅操控 沈孤鸿", text)

    def test_battle_start_and_advance_attach_engine_report(self):
        slot, started = self._start_battle()
        self.assertEqual(started.get("界面"), "battle-ui")
        self.assertEqual(started.get("渲染模式"), "LLM")
        self.assertEqual(started.get("渲染文本"), "\n\n".join(
            _txt(part) for part in (started.get("战报"), started.get("玩家界面")) if _txt(part)))

        settled = run_engine(slot, {
            "行为": [{"类型": "战斗-使用武学", "武学": "不存在的武学"}]},
            "go", self.save_dir)
        self.assertNotIn("界面", settled)
        self.assertIn("无法执行", settled.get("战报", ""))
        rejected = run_engine(slot, {
            "行为": [{"类型": "战斗-推进", "战报文本": "GM 改写"}],
            "当前剧情": ""}, "judge", self.save_dir)
        self.assertIn("不再接受 战报文本", rejected.get("错误", ""))
        advanced = run_engine(slot, {
            "行为": [{"类型": "战斗-推进", "回合详情": settled.get("回合详情") or []}],
            "当前剧情": ""}, "judge", self.save_dir)
        self.assertEqual(advanced.get("界面"), "battle-ui")
        self.assertEqual(advanced.get("战报"), settled.get("战报"))
        self.assertEqual(advanced.get("渲染文本"), "\n\n".join(
            _txt(part) for part in (advanced.get("战报"), advanced.get("玩家界面")) if _txt(part)))

    def test_direct_go_victory_attaches_battle_end_markdown(self):
        slot, _ = self._start_battle()
        self._rewrite_battle_hp(slot, player_hp=1000000, enemy_hp=0)
        ended = run_engine(slot, {"行为": [{"类型": "战斗-休息"}]}, "go", self.save_dir)
        self.assertEqual(ended.get("界面"), "battle-end-ui")
        self.assertEqual(ended.get("渲染模式"), "LLM")
        self.assertTrue(ended.get("渲染文本"))
        self.assertIn(ended.get("战报", ""), ended["渲染文本"])
        self.assertIn("### 【处决裁定】", ended["渲染文本"])
        self.assertIn("路不平", ended["渲染文本"])

    def test_gm_error_not_rendered_for_player(self):
        run_engine(self.slot, {"行为": [{"类型": "交谈观察"}]}, "go", self.save_dir)
        err = run_engine(self.slot, {"行为": [], "当前剧情": "路过。",
                                     "场景要素": "非法"}, "judge", self.save_dir)
        self.assertEqual(err.get("界面"), "exploration-ui")
        self.assertTrue(err.get("错误"))
        self.assertNotIn("渲染文本", err)
        # 修正后重调正常挂载（落点为驿站功能场景，要素须含功能NPC+特殊指令）
        # 主体用「驿丞何九」验证前缀匹配放宽
        ok = run_engine(self.slot, {"行为": [], "当前剧情": "夜色渐沉。",
                                    "场景要素": [
                                        {"主体": "海风", "描写": "咸腥扑面"},
                                        {"主体": "驿丞何九", "描写": "案后整理文书",
                                         "特殊指令": [{"名称": "远行（舟车）", "可用": True}]},
                                    ]}, "judge", self.save_dir)
        self.assertIn("渲染文本", ok)

    def test_dsh_mode_empty_text_structured_intact(self):
        back = run_engine(self.slot, {"行为": [{"类型": "返回游戏"}]}, "go", self.save_dir, mode="dsh")
        self.assertEqual(back.get("渲染模式"), "dsh")
        self.assertEqual(back.get("渲染文本"), "")
        for key in ("剧情描写", "场景要素", "队伍状态", "相邻出口", "当前位置"):
            self.assertIn(key, back)
        panel = run_engine(self.slot, {"行为": [{"类型": "查看地图"}]}, "go", self.save_dir, mode="dsh")
        self.assertEqual(panel.get("渲染文本"), "")
        self.assertIn("场景图", panel)
        self.assertNotIn("邻接图", panel)
        mastery = run_engine(self.slot, {"行为": [{"类型": "武学精进", "武学": "太乙玄门剑"}]},
                             "go", self.save_dir, mode="dsh")
        self.assertEqual(mastery.get("渲染文本"), "")
        self.assertIn("十境表数据", mastery)
        self.assertNotIn("十境表", mastery)

    def test_webui_mode_keeps_structured_and_renders(self):
        panel = run_engine(self.slot, {"行为": [{"类型": "查看地图"}]}, "go", self.save_dir, mode="WEB_UI")
        self.assertEqual(panel.get("渲染模式"), "WEB_UI")
        self.assertIn("场景图", panel)
        self.assertIn("邻接图", panel)
        self.assertTrue(panel["渲染文本"])
        mastery = run_engine(self.slot, {"行为": [{"类型": "武学精进", "武学": "太乙玄门剑"}]},
                             "go", self.save_dir, mode="WEB_UI")
        self.assertIn("十境表数据", mastery)
        self.assertIn("十境表", mastery)
        self.assertTrue(mastery["渲染文本"])

    def test_title_ui_engine_flow_and_validation(self):
        title = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, "go", self.save_dir)
        self.assertEqual(title.get("界面"), "title-ui")
        self.assertEqual(title.get("标题状态"), "主页")
        self.assertEqual(title.get("版本"), "0.9.8")
        self.assertIn("渲染文本", title)
        dsh_title = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, "go", self.save_dir, mode="dsh")
        self.assertEqual(dsh_title.get("渲染文本"), "")
        self.assertEqual(dsh_title.get("版本"), "0.9.8")
        web_title = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, "go", self.save_dir, mode="WEB_UI")
        self.assertTrue(web_title.get("渲染文本"))
        self.assertIn("存档列表", web_title)

        started = run_engine(0, {"行为": [{"类型": "标题-操作", "操作": "开始创建"}]},
                             "go", self.save_dir)
        self.assertEqual(started.get("标题状态"), "创建-立名")
        draft = started["创建草稿"]
        invalid = run_engine(0, {"行为": [{
            "类型": "标题-操作", "操作": "提交立名", "创建草稿": draft,
            "名称": "苏晚照", "性别": "女", "年龄": 15,
        }]}, "go", self.save_dir)
        self.assertEqual(invalid.get("界面"), "title-ui")
        self.assertEqual(invalid.get("标题状态"), "创建-立名")
        self.assertIn("16～80", invalid.get("校验提示", ""))
        self.assertIn("16～80", invalid.get("渲染文本", ""))

        valid = run_engine(0, {"行为": [{
            "类型": "标题-操作", "操作": "提交立名", "创建草稿": draft,
            "名称": "苏晚照", "性别": "女", "年龄": 21,
        }]}, "go", self.save_dir)
        self.assertEqual(valid.get("标题状态"), "创建-资质")
        confirmed = run_engine(0, {"行为": [{
            "类型": "标题-操作", "操作": "确认资质", "创建草稿": valid["创建草稿"],
        }]}, "go", self.save_dir)
        self.assertEqual(confirmed.get("标题状态"), "创建-武学")
        self.assertEqual(len(confirmed.get("初始武学列表") or []), 6)

        detail = run_engine(0, {"行为": [{
            "类型": "标题-操作", "操作": "武学详情", "创建草稿": confirmed["创建草稿"],
            "武学": "太乙玄门剑",
        }]}, "go", self.save_dir)
        self.assertEqual(detail.get("标题状态"), "创建-武学详情")
        self.assertEqual((detail.get("武学详情") or {}).get("名称"), "太乙玄门剑")
        self.assertIn("| Lv10 |", detail.get("渲染文本", ""))

    def test_compact_character_creation_keeps_full_role_path_compatible(self):
        title = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, "go", self.save_dir)
        slot = title["next_slot"]
        draft = title_flow.fresh_draft()
        draft.update({"名称": "柳藏锋", "性别": "男", "年龄": 21})
        created = run_engine(slot, {"行为": [{
            "类型": "创建角色", "创建草稿": draft, "初始武学": "太乙玄门剑",
        }]}, "go", self.save_dir)
        self.assertFalse(created.get("错误"), created)
        self.assertEqual(created.get("槽位"), slot)
        self.assertEqual(created.get("turn_state"), "AWAITING_JUDGE")
        changes = [item.get("变更") for item in created.get("结算") or []]
        self.assertIn("获得 长剑", changes)
        self.assertIn("学会 太乙玄门剑", changes)


if __name__ == "__main__":
    unittest.main()
