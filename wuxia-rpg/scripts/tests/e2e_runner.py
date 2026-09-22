#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine go/judge 端到端基本功能测试。

隔离运行：WUXIA_RPG_SAVE_DIR 指向临时目录，不污染真实存档。
覆盖基本功能：建档 / 门厅哨兵 / go-judge 两步式 / 任务草稿 / judge 回滚 /
judge 顶层校验 / 场景登记校验 / 查询类带界面 / 战斗流程 / 判定 CLI / 数据查询 CLI。
用法：python3 scripts/tests/e2e_runner.py（退出码 0=全过）
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))      # scripts/tests/
SCRIPTS = os.path.dirname(HERE)                         # scripts/
sys.path.insert(0, SCRIPTS)

ENGINE = os.path.join(SCRIPTS, "engine.py")

from common import dao as dq
from engine import OPENING_ERA_TEMPLATE
from store import save_manager as sm
from store import turn_state
from store import quest_drafts
from store import scene_drafts
from world import scene as sc

FAILED = []

_BATTLE_JUDGE_ACTIONS = {"战斗-开始", "战斗-触发", "战斗-推进"}


def judge_elements(slot, save_dir, changes=None):
    """按 judge 落定后位置构造最小合法场景要素：优先取行为中玩家「抵达」的目的地
    （功能NPC校验在变更应用后按新位置执行）；功能场景须含绑定功能NPC与全套特殊指令。"""
    position = None
    for action in changes or []:
        if isinstance(action, dict) and action.get("类型") == "抵达" and not action.get("角色"):
            position = action.get("位置") or action.get("目的地")
    if not position:
        position = (sm.read_explore(slot, save_dir) or {}).get("当前位置") or ""
    region, _, scene = position.partition("·")
    stype = sc.scene_type(slot, region, scene)
    npc = sc.scene_npc(slot, region, scene)
    commands = {"驿站": ["远行（舟车）"], "店铺": ["购买", "出售"], "客栈": ["投宿"]}.get(stype)
    if npc and commands:
        return [{"主体": npc, "描写": "当值",
                 "特殊指令": [{"名称": c, "可用": True} for c in commands]}]
    return [{"主体": "四周", "描写": "一切如常"}]


def run_engine(slot, payload, cmd="go", save_dir=None, fill_elements=True):
    """subprocess 调 engine.py go/judge，stdin 传 JSON，返回解析后的 dict。"""
    payload = {"槽位": slot, **payload}
    if cmd == "judge":
        payload.setdefault("提及地点", [])
        # 场景要素为非战斗 judge 必填：测试骨架按落定位置自动补全（校验用例传 fill_elements=False）
        battle = any(isinstance(a, dict) and a.get("类型") in _BATTLE_JUDGE_ACTIONS
                     for a in payload.get("行为") or [])
        if fill_elements and "场景要素" not in payload and not battle:
            payload["场景要素"] = judge_elements(slot, save_dir, payload.get("行为"))
    env = dict(os.environ)
    if save_dir:
        env["WUXIA_RPG_SAVE_DIR"] = save_dir
    p = subprocess.run([sys.executable, ENGINE, cmd],
                       input=json.dumps(payload, ensure_ascii=False),
                       capture_output=True, text=True, env=env, timeout=60)
    try:
        result = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"_rc": p.returncode or -1, "_stderr": p.stderr[-500:], "_stdout": p.stdout[:500]}
    if p.returncode != 0 and isinstance(result, dict):
        result["_rc"] = p.returncode
        result["_stderr"] = p.stderr[-500:]
    return result


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILED.append(name)


def char(name, faction="江湖"):
    """构造最小合规角色 dict（通过 character_schema 严格校验）。"""
    return {
        "名称": name, "阵营": faction, "性别": "男", "年龄": 20, "武功定位": "武者",
        "一级属性": {"根骨": 10, "力道": 10, "身法": 10, "内功": 10},
        "极性": {"内功": "中", "力道": "中", "身法": "中", "根骨": "中"},
        "铜钱": 1000, "物品": ["玉佩"],
        "武学": [{"名称": "百缠手", "等级": 1}],
        "武艺": {"搏击": 10, "剑法": 0, "刀法": 0, "长兵": 0, "奇门": 0, "暗器": 0},
        "技艺": {"音律": 0, "弈棋": 0, "诗书": 0, "绘画": 0, "医术": 0, "博物": 0},
        "装备": {}, "人设": "测试角色",
    }


def quest_blueprint(reward_prefix="e2e-ledger", fact="item:e2e_ledger.authenticity@world",
                    name="回归账册"):
    return fact, {
        "版本": 1, "名称": name,
        "引子": "一册账册来历可疑。", "隐藏目标": "查清账册真伪",
        "事实定义": [
            {"事实键": fact, "描述": "回归账册的真实真伪", "值类型": "enum", "可选值": ["authentic", "forged"]},
        ],
        "起始节点": ["heard"],
        "节点": [
            {"节点ID": "heard", "关闭条件": None, "关闭描述": None, "完成条件": {}, "完成摘要": "得到账册线索。",
             "后继节点": ["authentic", "forged", "follow-up"]},
            {"节点ID": "follow-up", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
             "完成条件": {"node": "heard", "completed": True}, "完成摘要": "余波待查。",
             "扩展点": True},
            {"节点ID": "authentic", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
             "完成条件": {"fact": fact, "eq": "authentic"},
             "完成摘要": "确认账册为真。", "终局": True,
             "奖励": {"奖励ID": f"{reward_prefix}:reward", "描述": "体力+5",
                     "状态变更": [{"类型": "体力", "操作": "加", "值": 5}]}},
            {"节点ID": "forged", "关闭条件": None, "关闭描述": None, "前置节点": ["heard"],
             "完成条件": {"fact": fact, "eq": "forged"},
             "完成摘要": "确认账册为伪。", "终局": True},
        ],
    }


def _has_item(slot, name, save_dir, expected=True):
    """校验玩家背包是否含某物品。expected=True 期望含、False 期望不含。"""
    player = (sm.read_meta(slot, save_dir) or {}).get("角色名")
    if not player:
        return not expected
    ch = dq.read_character_file(player, data_dir=sm.slot_data_dir(slot, save_dir))
    bag = []
    for it in (ch.get("物品") or []):
        if isinstance(it, str):
            bag.append(it)
        elif isinstance(it, dict):
            bag.append(it.get("名称"))
    return (name in bag) == expected


def _read_char(slot, name, save_dir):
    return dq.read_character_file(name, data_dir=sm.slot_data_dir(slot, save_dir)) or {}


def _item_count(character, name):
    return sum(1 for item in (character.get("物品") or [])
               if item == name or (isinstance(item, dict) and item.get("名称") == name))


def _copper(slot, save_dir):
    """取玩家铜钱。"""
    player = (sm.read_meta(slot, save_dir) or {}).get("角色名")
    if not player:
        return 0
    ch = _read_char(slot, player, save_dir)
    return int(ch.get("铜钱", ch.get("银两", 0)) or 0) if ch else 0


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["WUXIA_RPG_SAVE_DIR"] = tmp
        # dao.SAVE_DIR / sm.DEFAULT_SAVE_DIR 在 import 时固化，此处 patch 使本进程读取一致
        sm.DEFAULT_SAVE_DIR = tmp
        dq.SAVE_DIR = tmp

        # -------- 样例1：建档 --------
        print("== 样例1 建档 ==")
        title = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, save_dir=tmp)
        create_slot = title.get("next_slot")
        check("开始游戏返回 next_slot", create_slot == 1,
              f"title={json.dumps(title, ensure_ascii=False)[:200]}")
        check("标题界面由 engine 直出完整 Markdown",
              title.get("界面") == "title-ui" and title.get("版本")
              and isinstance(title.get("渲染文本"), str) and title.get("渲染文本") != "",
              f"title={json.dumps(title, ensure_ascii=False)[:200]}")
        wizard = run_engine(0, {"行为": [{"类型": "标题-操作", "操作": "开始创建"}]}, save_dir=tmp)
        check("标题创建草稿无状态返回",
              wizard.get("标题状态") == "创建-立名" and isinstance(wizard.get("创建草稿"), dict),
              f"wizard={json.dumps(wizard, ensure_ascii=False)[:200]}")
        # 严格 schema 校验：误名字段（同级极性）建档打回，不占用槽位
        bad_hero = char("误名侠")
        bad_hero["同级极性"] = bad_hero.pop("极性")
        before_slots = len(sm.list_all_saves(save_dir=tmp))
        r = run_engine(create_slot, {"行为": [{"类型": "创建角色", "角色": bad_hero}]}, save_dir=tmp)
        check("建档拒绝误名极性字段",
              r.get("错误") is None and any("同级极性" in str(x.get("msg") or "")
                                            for x in r.get("结算") or []),
              f"r={json.dumps(r, ensure_ascii=False)[:200]}")
        check("schema 打回不占用槽位", len(sm.list_all_saves(save_dir=tmp)) == before_slots,
              f"{before_slots} -> {len(sm.list_all_saves(save_dir=tmp))}")
        r = run_engine(create_slot, {"行为": [{"类型": "创建角色", "角色": char("沈孤鸿")}]}, save_dir=tmp)
        check("建档成功无错", r.get("错误") is None and "_rc" not in r, f"r={json.dumps(r, ensure_ascii=False)[:200]}")
        slot = (r.get("结算") or [{}])[0].get("新建slot")
        check("返回新建slot", slot is not None, f"r={json.dumps(r, ensure_ascii=False)[:200]}")
        check("建档带落点", (r.get("结算") or [{}])[0].get("落点"), f"r={json.dumps(r, ensure_ascii=False)[:200]}")
        check("创建角色后进入待开场 judge",
              r.get("turn_state") == turn_state.AWAITING_JUDGE
              and turn_state.read_state(slot, tmp)["origin"] == "创建角色",
              f"r={json.dumps(r, ensure_ascii=False)[:200]}")
        preset_state = sm.read_quest_state(slot, tmp)
        preset_names = set((preset_state.get("definitions") or {}).keys())
        check("新档载入全部隐藏预设任务",
              len(preset_names) == 19
              and all(runtime.get("lifecycle") == "hidden"
                      for runtime in (preset_state.get("runtimes") or {}).values()),
              f"quests={len(preset_names)}")
        check("隐藏预设不污染玩家线索栏",
              (sm.read_explore(slot, tmp) or {}).get("任务摘要及进度") == [],
              f"explore={json.dumps(sm.read_explore(slot, tmp), ensure_ascii=False)[:250]}")
        region = str((r.get("结算") or [{}])[0].get("落点") or "").split("·", 1)[0]
        hints = r.get("GM线索提示") or []
        check("建档未接触由头不暴露隐藏线索",
              hints == [],
              f"region={region}, hints={json.dumps(hints, ensure_ascii=False)[:250]}")
        blocked = run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "周遭"}]}, save_dir=tmp)
        check("开场 judge 前拒绝新 go", blocked.get("状态冲突") == "go_already_committed",
              f"blocked={json.dumps(blocked, ensure_ascii=False)[:200]}")
        opening_actions = [
            {"类型": "事实-写入", "事实": "quest:v3:taihu.hook@world",
             "值": True, "状态": "verified"},
            {"类型": "线索-发现", "名称": "太湖风波"},
        ]
        rejected = run_engine(slot, {"行为": opening_actions,
                                     "当前剧情": "沈孤鸿初入江湖。"}, cmd="judge", save_dir=tmp)
        check("开场 judge 缺固定开场白被打回",
              "开场白" in str(rejected.get("错误") or "")
              and rejected.get("turn_state") == turn_state.AWAITING_JUDGE,
              f"rejected={json.dumps(rejected, ensure_ascii=False)[:200]}")
        opening = run_engine(slot, {"行为": opening_actions,
                                    "当前剧情": OPENING_ERA_TEMPLATE
                                    + "\n\n沈孤鸿初入江湖，在城中见招勇告示。"},
                             cmd="judge", save_dir=tmp)
        check("创建角色开场 judge 接通", opening.get("错误") is None
              and opening.get("界面") == "exploration-ui",
              f"opening={json.dumps(opening, ensure_ascii=False)[:200]}")
        check("开场 judge 后回到 READY", opening.get("turn_state") == turn_state.READY,
              f"opening={json.dumps(opening, ensure_ascii=False)[:200]}")
        opened_state = sm.read_quest_state(slot, tmp)
        opened_runtime = (opened_state.get("runtimes") or {}).get("太湖风波") or {}
        player_clues = (sm.read_explore(slot, tmp) or {}).get("任务摘要及进度") or []
        check("由头写入后激活预设任务",
              opened_runtime.get("lifecycle") == "active"
              and opened_runtime.get("completed_node_ids") == ["entry"]
              and [item.get("名称") for item in player_clues] == ["太湖风波"],
              f"runtime={opened_runtime}, clues={player_clues}")

        # -------- 样例2：门厅哨兵 --------
        print("== 样例2 门厅哨兵 ==")
        # slot=0（未选存档）非门厅动作应被拒（存档列表不在 _LOBBY_SLOT0_ACTIONS）
        g = run_engine(0, {"行为": [{"类型": "存档列表"}]}, save_dir=tmp)
        check("门厅拒绝非门厅动作", g.get("错误") is not None or g.get("提示") is not None,
              f"g={json.dumps(g, ensure_ascii=False)[:200]}")
        # 门厅动作放行（开始游戏 不落盘 slot 0）
        g2 = run_engine(0, {"行为": [{"类型": "开始游戏"}]}, save_dir=tmp)
        check("门厅放行门厅动作", g2.get("_rc") is None, f"g2={json.dumps(g2, ensure_ascii=False)[:200]}")

        # -------- 样例3：go/judge 两步式（赠送落盘） --------
        print("== 样例3 go/judge 两步式 ==")
        before_missing_target = sm.read_explore(slot, tmp) or {}
        missing_target = run_engine(slot, {"行为": [{"类型": "交谈观察"}]}, save_dir=tmp)
        after_missing_target = sm.read_explore(slot, tmp) or {}
        check("交谈观察缺少目标时拒绝且不结算",
              "须传入 目标" in str(missing_target.get("提示", ""))
              and before_missing_target == after_missing_target
              and missing_target.get("turn_state") == turn_state.READY,
              f"missing_target={json.dumps(missing_target, ensure_ascii=False)[:250]}")
        g = run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "周遭"}]}, save_dir=tmp)
        check("go 交谈观察无界面（需调 judge）", "界面" not in g, f"g={list(g.keys())}")
        check("无界面 go 带区域提示不带全图",
              bool(g.get("区域提示")) and "区域场景" not in g,
              f"提示={g.get('区域提示')}, 键={list(g.keys())}")
        check("go 后进入待 judge", g.get("turn_state") == turn_state.AWAITING_JUDGE, f"g={g}")
        duplicate = run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "周遭"}]}, save_dir=tmp)
        check("重复 go 被阶段门禁拒绝", duplicate.get("状态冲突") == "go_already_committed"
              and "go_result" not in duplicate,
              f"duplicate={json.dumps(duplicate, ensure_ascii=False)[:200]}")
        readonly = run_engine(slot, {"行为": [{"类型": "角色信息", "角色": "沈孤鸿"}]}, save_dir=tmp)
        check("待 judge 时仍允许只读 go", readonly.get("状态冲突") is None
              and readonly.get("turn_state") == turn_state.AWAITING_JUDGE,
              f"readonly={json.dumps(readonly, ensure_ascii=False)[:200]}")
        j = run_engine(slot, {"行为": [
            {"类型": "物品", "操作": "减", "角色": "沈孤鸿", "名": "玉佩", "数量": 1},
        ], "当前剧情": "沈孤鸿把玉佩收进怀里。"}, cmd="judge", save_dir=tmp)
        check("judge 正常落盘无错", j.get("错误") is None, f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        check("judge 返回 exploration-ui", j.get("界面") == "exploration-ui", f"界面={j.get('界面')}")
        check("judge 后回到 READY", j.get("turn_state") == turn_state.READY, f"j={j}")
        go_changes = [r.get("变更") for r in (g.get("结算") or []) if r.get("变更")]
        judged_changes = [r.get("变更") for r in (j.get("结算") or []) if r.get("变更")]
        check("只读 go 不覆盖待 judge 机制提示",
              bool(go_changes) and all(change in judged_changes for change in go_changes),
              f"go={go_changes}, judge={judged_changes}")
        check("落盘后玩家无玉佩", _has_item(slot, "玉佩", tmp, expected=False))
        g_npc = run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "石敬岩"}]}, save_dir=tmp)
        npc_contact = ((sm.read_world_facts(slot, tmp) or {}).get("records") or {}) \
            .get("character:石敬岩.contact@player") or {}
        check("交谈观察 NPC 目标自动记录接触事实",
              g_npc.get("错误") is None and npc_contact.get("value") is True,
              f"g_npc={json.dumps(g_npc, ensure_ascii=False)[:200]}, contact={npc_contact}")
        j_npc = run_engine(slot, {"行为": [], "当前剧情": "沈孤鸿与石敬岩攀谈数句。"},
                            cmd="judge", save_dir=tmp)
        check("NPC 交谈观察 judge 落盘无错", j_npc.get("错误") is None, f"j_npc={j_npc}")
        surroundings_contact = ((sm.read_world_facts(slot, tmp) or {}).get("records") or {}) \
            .get("character:周遭.contact@player")
        check("非 NPC 目标不记录接触事实", surroundings_contact is None,
              f"contact={surroundings_contact}")
        g_xu = run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "徐鸿儒"}]}, save_dir=tmp)
        check("接触徐鸿儒触发通天七剑入场提示",
              any(hint.get("类型") == "隐藏线索" and hint.get("线索") == "通天七剑"
                  for hint in (g_xu.get("GM线索提示") or [])),
              f"g_xu={json.dumps(g_xu, ensure_ascii=False)[:300]}")
        j_xu = run_engine(slot, {"行为": [{"类型": "线索-发现", "名称": "通天七剑"}],
                                 "当前剧情": "沈孤鸿与白发剑侠徐鸿儒交谈。"},
                          cmd="judge", save_dir=tmp)
        xu_runtime = ((sm.read_quest_state(slot, tmp) or {}).get("runtimes") or {}) \
            .get("通天七剑") or {}
        check("接触后可发现通天七剑", j_xu.get("错误") is None
              and xu_runtime.get("lifecycle") == "active",
              f"j_xu={json.dumps(j_xu, ensure_ascii=False)[:200]}, runtime={xu_runtime}")
        duplicate_judge = run_engine(slot, {"行为": [], "当前剧情": "重复裁定。"}, cmd="judge", save_dir=tmp)
        check("重复 judge 被阶段门禁拒绝", duplicate_judge.get("状态冲突") == "judge_not_expected",
              f"duplicate_judge={json.dumps(duplicate_judge, ensure_ascii=False)[:200]}")

        before_search = sm.read_explore(slot, tmp) or {}
        search = run_engine(slot, {"行为": [
            {"类型": "搜查翻找", "目标": "旧书柜"},
        ]}, save_dir=tmp)
        after_search = sm.read_explore(slot, tmp) or {}
        check("搜查翻找扣2体力2刻且进入待裁定", search.get("错误") is None
              and "界面" not in search
              and search.get("turn_state") == turn_state.AWAITING_JUDGE
              and after_search.get("体力") == int(before_search.get("体力", 0) or 0) - 2
              and after_search.get("当前时间") == int(before_search.get("当前时间", 0) or 0) + 2,
              f"before={before_search.get('当前时间'), before_search.get('体力')} "
              f"after={after_search.get('当前时间'), after_search.get('体力')} search={search}")
        search_judge = run_engine(slot, {
            "行为": [], "当前剧情": "沈孤鸿翻检旧书柜，没有放过任何夹层。",
        }, cmd="judge", save_dir=tmp)
        check("搜查翻找后 judge 恢复 READY",
              search_judge.get("错误") is None
              and search_judge.get("turn_state") == turn_state.READY,
              f"search_judge={json.dumps(search_judge, ensure_ascii=False)[:200]}")

        # -------- 样例3b：批量任务 prepare → judge 采用 --------
        print("== 样例3b 批量任务草稿采用 ==")
        g = run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "周遭"}]}, save_dir=tmp)
        fact, quest = quest_blueprint()
        second_fact, second_quest = quest_blueprint(
            "e2e-letter", "item:e2e_letter.authenticity@world", "回归密信"
        )
        prepared = run_engine(slot, {"任务": [
            {"操作": "创建", "蓝图": quest},
            {"操作": "创建", "蓝图": second_quest},
        ]}, cmd="quest-prepare", save_dir=tmp)
        prepared_names = [row.get("名称") for row in (prepared.get("任务") or [])]
        check("quest-prepare 返回同轮任务批次", prepared.get("ok") is True
              and prepared.get("turn_state") == turn_state.AWAITING_JUDGE
              and prepared_names == ["回归账册", "回归密信"],
              f"prepared={json.dumps(prepared, ensure_ascii=False)[:300]}")
        failed_adoption = run_engine(slot, {"行为": [
            {"类型": "线索-采用草稿", "名称列表": list(reversed(prepared_names))},
            {"类型": "不存在类型", "值": 1},
        ], "当前剧情": "本次裁定应整体失败。"}, cmd="judge", save_dir=tmp)
        failed_quests = sm.read_quest_state(slot, tmp).get("definitions", {})
        check("judge 失败保留任务草稿供重试", failed_adoption.get("错误") is not None
              and os.path.exists(quest_drafts.quest_drafts_path(slot, tmp))
              and "回归账册" not in failed_quests and "回归密信" not in failed_quests,
              f"failed={json.dumps(failed_adoption, ensure_ascii=False)[:300]}")
        stamina_before = int((sm.read_explore(slot, tmp) or {}).get("体力", 0) or 0)
        adopted = run_engine(slot, {"行为": [
            {"类型": "线索-采用草稿", "名称列表": prepared_names},
            {"类型": "事实", "事实": fact, "值": "authentic"},
            {"类型": "事实", "事实": second_fact, "值": "authentic"},
        ], "当前剧情": "沈孤鸿查明账册与密信皆为真本。"}, cmd="judge", save_dir=tmp)
        quest_state = sm.read_quest_state(slot, tmp)
        world_facts = sm.read_world_facts(slot, tmp)
        check("judge 原子采用多个任务并归约事实奖励", adopted.get("错误") is None
              and quest_state.get("runtimes", {}).get("回归账册", {}).get("lifecycle") == "ended"
              and quest_state.get("runtimes", {}).get("回归密信", {}).get("lifecycle") == "ended"
              and world_facts.get("records", {}).get(fact, {}).get("value") == "authentic"
              and world_facts.get("records", {}).get(second_fact, {}).get("value") == "authentic"
              and int((sm.read_explore(slot, tmp) or {}).get("体力", 0) or 0) == min(100, stamina_before + 10),
              f"adopted={json.dumps(adopted, ensure_ascii=False)[:350]}")
        check("judge 成功后清理本轮任务草稿",
              not os.path.exists(quest_drafts.quest_drafts_path(slot, tmp)))

        # -------- 样例4：judge 回滚 --------
        print("== 样例4 judge 回滚 ==")
        run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "周遭"}]}, save_dir=tmp)
        copper_before = _copper(slot, tmp)
        j = run_engine(slot, {"行为": [
            {"类型": "铜钱", "操作": "加", "角色": "沈孤鸿", "值": 100},
            {"类型": "不存在类型", "操作": "加", "角色": "沈孤鸿", "值": 1},
        ], "当前剧情": ".."}, cmd="judge", save_dir=tmp)
        check("judge 非法类型 → gm_error", j.get("错误") is not None and "不存在类型" in str(j.get("错误", "")),
              f"错误={j.get('错误')}")
        check("回滚后铜钱不变", _copper(slot, tmp) == copper_before, f"{copper_before}→{_copper(slot, tmp)}")

        print("== 样例4b 写角色武学校验 ==")
        empty_npc = char("无艺客")
        empty_npc["武学"] = []
        j = run_engine(slot, {"行为": [
            {"类型": "写角色", "角色": empty_npc},
        ], "当前剧情": "无艺客出现在路旁。"}, cmd="judge", save_dir=tmp)
        check("judge 拒绝武学为空的角色",
              j.get("错误") is not None and "武学不能为空" in str(j.get("错误", "")),
              f"错误={j.get('错误')}")
        check("武学为空的角色不落盘",
              dq.read_character_file("无艺客", data_dir=sm.slot_data_dir(slot, tmp)) is None)

        # 严格 schema 校验：误名字段（同级极性）当场打回，不落盘
        bad_npc = char("误名客")
        bad_npc["同级极性"] = bad_npc.pop("极性")
        j = run_engine(slot, {"行为": [
            {"类型": "写角色", "角色": bad_npc},
        ], "当前剧情": "误名客出现在路旁。"}, cmd="judge", save_dir=tmp)
        check("写角色拒绝误名极性字段",
              j.get("错误") is not None and "极性" in str(j.get("错误", "")),
              f"错误={j.get('错误')}")
        check("schema 打回的角色不落盘",
              dq.read_character_file("误名客", data_dir=sm.slot_data_dir(slot, tmp)) is None)

        skilled_npc = char("有艺客")
        skilled_npc["武学"] = [{"名称": "百缠手", "等级": 1}]
        j = run_engine(slot, {"行为": [
            {"类型": "写角色", "角色": skilled_npc},
            {"类型": "不存在类型", "值": 1},
        ], "当前剧情": "有艺客出现在路旁。"}, cmd="judge", save_dir=tmp)
        check("写角色后续变化失败时整轮报错", j.get("错误") is not None,
              f"错误={j.get('错误')}")
        check("写角色后续变化失败时新角色不落盘",
              dq.read_character_file("有艺客", data_dir=sm.slot_data_dir(slot, tmp)) is None)

        j = run_engine(slot, {"行为": [
            {"类型": "写角色", "角色": skilled_npc},
        ], "当前剧情": "有艺客出现在路旁。"}, cmd="judge", save_dir=tmp)
        check("judge 接受武学非空角色", j.get("错误") is None,
              f"错误={j.get('错误')}")
        check("武学非空的角色正常落盘",
              dq.read_character_file("有艺客", data_dir=sm.slot_data_dir(slot, tmp)) is not None)

        # -------- 样例4c：复合 go 行为 --------
        print("== 样例4c 复合 go 行为 ==")
        before = sm.read_explore(slot, tmp) or {}
        rest = run_engine(slot, {"行为": [{"类型": "休息", "等级": "露宿",
                                            "时长": 8, "免费": True}]}, save_dir=tmp)
        after = sm.read_explore(slot, tmp) or {}
        check("休息经 go 结算时间与体力", rest.get("错误") is None
              and after.get("当前时间") == int(before.get("当前时间", 0) or 0) + 8
              and after.get("体力") == min(100, int(before.get("体力", 0) or 0) + 10),
              f"before={before.get('当前时间'), before.get('体力')} after={after.get('当前时间'), after.get('体力')}")
        prepared_scene = run_engine(slot, {"场景": [
            {"操作": "登记", "区域": "苏州", "场景": "终点"},
            {"操作": "登记", "区域": "苏州", "场景": "起点",
             "方位出口": {"东": "终点"}},
        ]}, cmd="scene-prepare", save_dir=tmp)
        check("休息后可准备行旅场景", prepared_scene.get("ok") is True,
              f"prepared={json.dumps(prepared_scene, ensure_ascii=False)[:250]}")
        j = run_engine(slot, {"行为": [
            {"类型": "场景-采用草稿"},
            {"类型": "抵达", "位置": "苏州·起点"},
            {"类型": "物品", "操作": "增", "角色": "沈孤鸿", "名": "小还丹", "数量": 2},
            {"类型": "气血", "操作": "设", "角色": "沈孤鸿", "值": 1},
        ], "当前剧情": "沈孤鸿歇息后抵达行旅起点。"}, cmd="judge", save_dir=tmp)
        check("休息后 judge 建立行旅测试状态", j.get("错误") is None,
              f"j={json.dumps(j, ensure_ascii=False)[:250]}")

        before = sm.read_explore(slot, tmp) or {}
        travel = run_engine(slot, {"行为": [{"类型": "远行（徒步）", "目的地": "终点"}]}, save_dir=tmp)
        after = sm.read_explore(slot, tmp) or {}
        check("徒步远行经 mutation 结算", travel.get("错误") is None
              and after.get("当前位置") == "苏州·终点"
              and after.get("当前时间") == int(before.get("当前时间", 0) or 0) + 4
              and after.get("体力") == int(before.get("体力", 0) or 0) - 5,
              f"travel={json.dumps(travel, ensure_ascii=False)[:200]}, after={after}")
        run_engine(slot, {"行为": [], "当前剧情": "沈孤鸿徒步抵达终点。"}, cmd="judge", save_dir=tmp)

        player_before = _read_char(slot, "沈孤鸿", tmp)
        state_before = sm.read_explore(slot, tmp) or {}
        used = run_engine(slot, {"行为": [{"类型": "使用物品", "物品": "小还丹",
                                            "目标": "沈孤鸿"}]}, save_dir=tmp)
        player_after = _read_char(slot, "沈孤鸿", tmp)
        state_after = sm.read_explore(slot, tmp) or {}
        check("使用物品结算成本、效果与消耗", used.get("错误") is None
              and _item_count(player_after, "小还丹") == _item_count(player_before, "小还丹") - 1
              and int(player_after.get("气血", 0) or 0) > 1
              and state_after.get("当前时间") == int(state_before.get("当前时间", 0) or 0) + 1
              and state_after.get("体力") == int(state_before.get("体力", 0) or 0) - 1,
              f"used={json.dumps(used, ensure_ascii=False)[:300]}, "
              f"items={_item_count(player_before, '小还丹')}→{_item_count(player_after, '小还丹')}, "
              f"hp={player_before.get('气血')}→{player_after.get('气血')}, "
              f"state={state_before.get('当前时间'), state_before.get('体力')}→"
              f"{state_after.get('当前时间'), state_after.get('体力')}")
        run_engine(slot, {"行为": [], "当前剧情": "沈孤鸿服下小还丹。"}, cmd="judge", save_dir=tmp)

        giver_before = _item_count(_read_char(slot, "沈孤鸿", tmp), "小还丹")
        receiver_before = _item_count(_read_char(slot, "有艺客", tmp), "小还丹")
        gifted = run_engine(slot, {"行为": [{"类型": "赠与物品", "物品": "小还丹",
                                              "受赠者": "有艺客", "数量": 1}]}, save_dir=tmp)
        giver_after = _item_count(_read_char(slot, "沈孤鸿", tmp), "小还丹")
        receiver_after = _item_count(_read_char(slot, "有艺客", tmp), "小还丹")
        check("赠与经 mutation 转移物品", gifted.get("错误") is None
              and giver_after == giver_before - 1
              and receiver_after == receiver_before + 1,
              f"gifted={json.dumps(gifted, ensure_ascii=False)[:300]}, "
              f"player={giver_before}→{giver_after}, npc={receiver_before}→{receiver_after}")
        run_engine(slot, {"行为": [], "当前剧情": "有艺客收下丹药。"}, cmd="judge", save_dir=tmp)

        copper_before = _copper(slot, tmp)
        bought = run_engine(slot, {"行为": [{"类型": "购买", "卖家": "有艺客",
                                              "物品": "玉佩", "数量": 1, "价格": 1,
                                              "商人": False}]}, save_dir=tmp)
        check("个人购买经 mutation 同步资产", bought.get("错误") is None
              and _has_item(slot, "玉佩", tmp)
              and _copper(slot, tmp) == copper_before - 1,
              f"bought={json.dumps(bought, ensure_ascii=False)[:200]}")
        run_engine(slot, {"行为": [], "当前剧情": "沈孤鸿买下玉佩。"}, cmd="judge", save_dir=tmp)

        copper_before = _copper(slot, tmp)
        sold = run_engine(slot, {"行为": [{"类型": "出售", "买家": "有艺客",
                                            "物品": "玉佩", "数量": 1, "价格": 1,
                                            "商人": False}]}, save_dir=tmp)
        check("个人出售经 mutation 同步资产", sold.get("错误") is None
              and _has_item(slot, "玉佩", tmp, expected=False)
              and _copper(slot, tmp) == copper_before + 1,
              f"sold={json.dumps(sold, ensure_ascii=False)[:200]}")
        if sold.get("turn_state") == turn_state.AWAITING_JUDGE:
            run_engine(slot, {"行为": [], "当前剧情": "沈孤鸿将玉佩售回。"}, cmd="judge", save_dir=tmp)

        player_before = _read_char(slot, "沈孤鸿", tmp)
        explore_before = sm.read_explore(slot, tmp) or {}
        cache_before = sm.read_merchant_cache(slot, tmp)
        failed_trade = run_engine(slot, {"行为": [
            {"类型": "出售", "买家": "测试商人", "物品": "小还丹", "数量": 1,
             "价格": 1, "商人": True},
            {"类型": "赠与物品", "物品": "并不存在的物品", "受赠者": "有艺客", "数量": 1},
        ]}, save_dir=tmp)
        player_after = _read_char(slot, "沈孤鸿", tmp)
        explore_after = sm.read_explore(slot, tmp) or {}
        cache_after = sm.read_merchant_cache(slot, tmp)
        check("后续 action 失败时商人交易整批回滚", failed_trade.get("提示") is not None
              and player_after == player_before
              and explore_after == explore_before
              and cache_after == cache_before,
              f"failed_trade={json.dumps(failed_trade, ensure_ascii=False)[:500]}, "
              f"player_equal={player_after == player_before}, "
              f"explore_equal={explore_after == explore_before}, cache_equal={cache_after == cache_before}, "
              f"items={_item_count(player_before, '小还丹')}→{_item_count(player_after, '小还丹')}, "
              f"copper={player_before.get('铜钱')}→{player_after.get('铜钱')}")

        # -------- 样例5：judge 顶层校验 --------
        print("== 样例5 judge 顶层校验 ==")
        run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "周遭"}]}, save_dir=tmp)
        j = run_engine(slot, {"行为": [], "当前剧情": "x", "非法字段": 1}, cmd="judge", save_dir=tmp)
        check("judge 拒绝非预期顶层字段", j.get("错误") is not None and "非预期字段" in str(j.get("错误", "")),
              f"错误={j.get('错误')}")
        check("顶层校验属 gm_error", j.get("gm_error") is True or "非法" in str(j.get("错误", "")),
              f"resp={json.dumps(j, ensure_ascii=False)[:200]}")

        print("== 样例5b 场景要素必填 ==")
        # 样例5 的 judge 失败后仍处 AWAITING_JUDGE，同一轮直接复测要素门禁
        j = run_engine(slot, {"行为": [], "当前剧情": "未带场景要素。"}, cmd="judge",
                       save_dir=tmp, fill_elements=False)
        check("judge 缺场景要素被打回", "须传非空「场景要素」" in str(j.get("错误") or ""),
              f"错误={j.get('错误')}")
        check("缺场景要素属 gm_error 形态", j.get("界面") == "exploration-ui"
              and j.get("turn_state") == turn_state.AWAITING_JUDGE,
              f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        j = run_engine(slot, {"行为": [], "当前剧情": "空场景要素。", "场景要素": []},
                       cmd="judge", save_dir=tmp, fill_elements=False)
        check("judge 空场景要素被打回", "须传非空「场景要素」" in str(j.get("错误") or ""),
              f"错误={j.get('错误')}")
        j = run_engine(slot, {"行为": [], "当前剧情": "补齐场景要素后通过。",
                              "场景要素": judge_elements(slot, tmp)}, cmd="judge", save_dir=tmp)
        check("带非空场景要素的 judge 通过", j.get("错误") is None,
              f"错误={j.get('错误')}")
        check("通过后回到 READY", j.get("turn_state") == turn_state.READY, f"j={j.get('turn_state')}")
        # 5b 收轮后为样例6 新开一轮（scene-prepare 须在 AWAITING_JUDGE 调用）
        run_engine(slot, {"行为": []}, save_dir=tmp)

        print("== 样例5c 死亡角色场景要素红线 ==")
        corpse = char("亡故客")
        corpse["武学"] = [{"名称": "百缠手", "等级": 1}]
        j = run_engine(slot, {"行为": [{"类型": "写角色", "角色": corpse}],
                              "当前剧情": "亡故客立于道旁。",
                              "场景要素": judge_elements(slot, tmp) + [{"主体": "亡故客", "描写": "立于道旁"}]},
                       cmd="judge", save_dir=tmp, fill_elements=False)
        check("生者可申报为场景要素主体", j.get("错误") is None, f"错误={j.get('错误')}")
        run_engine(slot, {"行为": []}, save_dir=tmp)  # 开新一轮：本轮判死，同轮收尾登场
        j = run_engine(slot, {"行为": [{"类型": "死亡", "角色": "亡故客"}],
                              "当前剧情": "亡故客倒地身亡。",
                              "场景要素": judge_elements(slot, tmp) + [{"主体": "亡故客", "描写": "倒地身亡"}]},
                       cmd="judge", save_dir=tmp, fill_elements=False)
        check("同轮判死者可同轮登场收尾", j.get("错误") is None, f"错误={j.get('错误')}")
        run_engine(slot, {"行为": []}, save_dir=tmp)
        j = run_engine(slot, {"行为": [],
                              "当前剧情": "亡故客竟又出现在眼前。",
                              "场景要素": judge_elements(slot, tmp) + [{"主体": "亡故客", "描写": "含笑而立"},
                                                                      {"主体": "仇家亡故客", "描写": "拦在路中"}]},
                       cmd="judge", save_dir=tmp, fill_elements=False)
        check("死亡角色裸名/头衔前缀申报被打回",
              "死亡角色不得申报为场景要素主体" in str(j.get("错误") or ""),
              f"错误={j.get('错误')}")
        check("死亡红线属 gm_error 形态", j.get("界面") == "exploration-ui"
              and j.get("turn_state") == turn_state.AWAITING_JUDGE,
              f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        j = run_engine(slot, {"行为": [],
                              "当前剧情": "亡故客的尸首仍倒卧道旁。",
                              "场景要素": judge_elements(slot, tmp) + [{"主体": "亡故客的尸首", "描写": "倒卧道旁"}]},
                       cmd="judge", save_dir=tmp, fill_elements=False)
        check("尸体表述（名+的+…）放行", j.get("错误") is None, f"错误={j.get('错误')}")

        print("== 样例5d 玩家主控场景要素红线 ==")
        # 先落盘相似长名角色 沈孤鸿声（校验先于状态变更，须在前一轮写盘）
        run_engine(slot, {"行为": []}, save_dir=tmp)
        j = run_engine(slot, {"行为": [{"类型": "写角色", "角色": char("沈孤鸿声")}],
                              "当前剧情": "沈孤鸿声现身江湖。",
                              "场景要素": judge_elements(slot, tmp) + [{"主体": "沈孤鸿声", "描写": "立于身侧"}]},
                       cmd="judge", save_dir=tmp, fill_elements=False)
        check("相似长名角色可正常申报", j.get("错误") is None, f"错误={j.get('错误')}")
        run_engine(slot, {"行为": []}, save_dir=tmp)
        j = run_engine(slot, {"行为": [],
                              "当前剧情": "沈孤鸿立在当场，佩剑映着微光。",
                              "场景要素": judge_elements(slot, tmp) + [
                                  {"主体": "沈孤鸿", "描写": "仗剑而立"},
                                  {"主体": "少侠沈孤鸿", "描写": "含笑而立"},
                                  {"主体": "沈孤鸿声", "描写": "立于身侧"},
                                  {"主体": "沈孤鸿的佩剑", "描写": "映着微光"}]},
                       cmd="judge", save_dir=tmp, fill_elements=False)
        check("主控裸名/头衔前缀申报被打回",
              "玩家主控不得申报为场景要素主体" in str(j.get("错误") or ""),
              f"错误={j.get('错误')}")
        check("主控红线属 gm_error 形态", j.get("界面") == "exploration-ui"
              and j.get("turn_state") == turn_state.AWAITING_JUDGE,
              f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        j = run_engine(slot, {"行为": [],
                              "当前剧情": "沈孤鸿声在侧，沈孤鸿的佩剑映着微光。",
                              "场景要素": judge_elements(slot, tmp) + [
                                  {"主体": "沈孤鸿声", "描写": "立于身侧"},
                                  {"主体": "沈孤鸿的佩剑", "描写": "映着微光"}]},
                       cmd="judge", save_dir=tmp, fill_elements=False)
        check("相似长名不误伤，随身物件（名+的+…）放行",
              j.get("错误") is None, f"错误={j.get('错误')}")
        # 5d 收轮后为样例6 新开一轮
        run_engine(slot, {"行为": []}, save_dir=tmp)

        # -------- 样例6：场景登记校验 --------
        print("== 样例6 场景登记校验 ==")
        prepared = run_engine(slot, {"场景": [{
            "操作": "登记", "区域": "苏州", "场景": "回环庭",
            "方位出口": {"北": "回环庭"},
        }]}, cmd="scene-prepare", save_dir=tmp)
        check("scene-prepare 拒绝场景出口指向自身",
              prepared.get("错误") is not None and "出口不能指向自身" in str(prepared.get("错误", "")),
              f"错误={prepared.get('错误')}")
        overlay = sm.read_map_overlay(slot, tmp)
        check("自环规划失败后不落盘",
              "回环庭" not in ((overlay.get("苏州") or {}).get("场景") or []),
              f"overlay={overlay.get('苏州')}")
        # 存在性校验：未知区域（真实少林寺山门位于嵩山）、未登记出口目标、跨区域名平移均打回
        prepared = run_engine(slot, {"场景": [{
            "操作": "登记", "区域": "少林寺", "场景": "知客寮",
            "方位出口": {"南": "少林寺山门"},
        }]}, cmd="scene-prepare", save_dir=tmp)
        check("scene-prepare 拒绝未知区域",
              prepared.get("错误") is not None and "未知区域" in str(prepared.get("错误", "")),
              f"错误={prepared.get('错误')}")
        prepared = run_engine(slot, {"场景": [{
            "操作": "登记", "区域": "苏州", "场景": "断头路",
            "方位出口": {"北": "凭空地点"},
        }]}, cmd="scene-prepare", save_dir=tmp)
        check("scene-prepare 拒绝出口目标未登记",
              prepared.get("错误") is not None and "未登记" in str(prepared.get("错误", "")),
              f"错误={prepared.get('错误')}")
        prepared = run_engine(slot, {"场景": [{
            "操作": "登记", "区域": "苏州", "场景": "断头路",
            "方位出口": {"北": "涌金门"},
        }]}, cmd="scene-prepare", save_dir=tmp)
        check("scene-prepare 拒绝跨区域目标平移",
              prepared.get("错误") is not None and "未登记" in str(prepared.get("错误", "")),
              f"错误={prepared.get('错误')}")
        prepared = run_engine(slot, {"场景": [
            {"操作": "登记", "区域": "苏州", "场景": "乙地"},
            {"操作": "登记", "区域": "苏州", "场景": "甲地",
             "方位出口": {"北": "乙地"}},
        ]}, cmd="scene-prepare", save_dir=tmp)
        check("scene-prepare 接受正常场景连接", prepared.get("ok") is True,
              f"错误={prepared.get('错误')}")
        j = run_engine(slot, {"行为": [{"类型": "场景-采用草稿"}],
                              "当前剧情": "测试正常场景登记。"}, cmd="judge", save_dir=tmp)
        check("judge 原子采纳正常场景连接", j.get("错误") is None,
              f"错误={j.get('错误')}")
        overlay = sm.read_map_overlay(slot, tmp).get("苏州") or {}
        check("正常连接组边双方位内联",
              any(set(e) == {"甲地.北", "乙地.南"} for e in overlay.get("边") or [])
              and "甲地" in (overlay.get("场景") or [])
              and "乙地" in (overlay.get("场景") or []),
              f"overlay={overlay}")

        print("== 样例6b 读档重置阶段 ==")
        run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "周遭"}]}, save_dir=tmp)
        _restore_fact, restore_quest = quest_blueprint(
            "restore-draft", "item:restore_ledger.authenticity@world", "读档草稿")
        restore_prepared = run_engine(slot, {
            "任务": [{"操作": "创建", "蓝图": restore_quest}],
        }, cmd="quest-prepare", save_dir=tmp)
        check("读档前可建立待裁定任务草稿", restore_prepared.get("ok") is True
              and os.path.exists(quest_drafts.quest_drafts_path(slot, tmp)),
              f"prepared={json.dumps(restore_prepared, ensure_ascii=False)[:250]}")
        scene_prepared = run_engine(slot, {"场景": [{
            "操作": "登记", "区域": "苏州", "场景": "待读档清理孤点",
        }]}, cmd="scene-prepare", save_dir=tmp)
        check("读档前可建立待裁定场景草稿", scene_prepared.get("ok") is True
              and os.path.exists(scene_drafts.scene_drafts_path(slot, tmp)),
              f"prepared={json.dumps(scene_prepared, ensure_ascii=False)[:250]}")
        saves = sm.list_saves(slot, tmp)
        target = saves[-1][0] if saves else None
        loaded = run_engine(slot, {"行为": [{"类型": "加载存档", "目标": target}]}, save_dir=tmp)
        check("待 judge 时允许读档恢复", target is not None and loaded.get("错误") is None,
              f"loaded={json.dumps(loaded, ensure_ascii=False)[:200]}")
        check("读档后阶段重置 READY", loaded.get("turn_state") == turn_state.READY,
              f"loaded={json.dumps(loaded, ensure_ascii=False)[:200]}")
        check("读档后清理任务草稿",
              not os.path.exists(quest_drafts.quest_drafts_path(slot, tmp)))
        check("读档后清理场景草稿",
              not os.path.exists(scene_drafts.scene_drafts_path(slot, tmp)))
        restored_presets = sm.read_quest_state(slot, tmp)
        restored_names = set((restored_presets.get("definitions") or {}).keys())
        check("读档保留全部预设任务状态",
              preset_names <= restored_names
              and (restored_presets.get("runtimes") or {}).get("太湖风波", {})
              .get("lifecycle") == "active",
              f"restored={len(restored_names)}")

        # -------- 样例7：查询类带界面 --------
        print("== 样例7 查询类带界面 ==")
        g = run_engine(slot, {"行为": [{"类型": "角色信息", "角色": "沈孤鸿"}]}, save_dir=tmp)
        check("角色信息带界面", g.get("界面") in ("character-ui", "exploration-ui"), f"界面={g.get('界面')}")
        g = run_engine(slot, {"行为": [{"类型": "查看背包", "角色": "沈孤鸿"}]}, save_dir=tmp)
        check("查看背包带界面", g.get("界面") in ("bag-ui", "exploration-ui"), f"界面={g.get('界面')}")

        # -------- 样例8：战斗流程 --------
        print("== 样例8 战斗流程 ==")
        # 前序物品测试曾主动压低气血；战斗流程夹具先恢复主控，避免状态伤害使首个休息动作直接败阵。
        player = _read_char(slot, "沈孤鸿", tmp)
        player["气血"] = max(1, int(player.get("气血上限", 0) or 999999))
        dq.update_char("沈孤鸿", player, data_dir=sm.slot_data_dir(slot, tmp))
        # 敌人用基线已有角色（避免重名校验）；攻击 go → 战斗-触发 → 战斗-开始
        enemy = "路不平"
        rnd0 = sm.read_round(slot, tmp)
        attack = run_engine(slot, {"行为": [{"类型": "攻击", "目标": enemy}]}, save_dir=tmp)
        check("攻击 go 进入待 judge", attack.get("turn_state") == turn_state.AWAITING_JUDGE,
              f"attack={json.dumps(attack, ensure_ascii=False)[:200]}")
        triggered = run_engine(slot, {"行为": [{"类型": "战斗-触发", "我方": ["沈孤鸿"],
                                                "敌方": [enemy], "允许逃跑": True}],
                                      "当前剧情": "路不平拦路！"}, cmd="judge", save_dir=tmp)
        check("战斗-触发进入待开始", triggered.get("界面") == "exploration-battle-ui"
              and triggered.get("turn_state") == turn_state.AWAITING_BATTLE_START,
              f"triggered={json.dumps(triggered, ensure_ascii=False)[:200]}")
        blocked_go = run_engine(slot, {"行为": [{"类型": "攻击", "目标": enemy}]}, save_dir=tmp)
        check("战前选择阶段拒绝 go", blocked_go.get("状态冲突") == "battle_start_expected",
              f"blocked_go={json.dumps(blocked_go, ensure_ascii=False)[:200]}")
        j = run_engine(slot, {"行为": [{"类型": "战斗-开始", "我方": ["沈孤鸿"], "敌方": [enemy],
                                       "允许逃跑": True, "操控方式": "玩家角色"}],
                           "当前剧情": "路不平拦路！"}, cmd="judge", save_dir=tmp)
        check("战斗-开始被接受无错", j.get("错误") is None and "_rc" not in j,
              f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        check("战斗-开始后回到 READY", j.get("turn_state") == turn_state.READY, f"j={j}")
        check("战斗-开始不推进轮次", sm.read_round(slot, tmp) == rnd0,
              f"{rnd0}→{sm.read_round(slot, tmp)}")
        # 战斗中 返回游戏 拒绝（战斗临时文件存在时）
        rg = run_engine(slot, {"行为": [{"类型": "返回游戏"}]}, save_dir=tmp)
        check("战斗中返回游戏拒绝", rg.get("提示") is not None or rg.get("错误") is not None,
              f"rg={json.dumps(rg, ensure_ascii=False)[:150]}")
        # 非终局战斗轮保留 go → judge 战斗-推进
        step = run_engine(slot, {"行为": [{"类型": "战斗-休息"}]}, save_dir=tmp)
        check("战斗操控 go 进入待 judge", step.get("turn_state") == turn_state.AWAITING_JUDGE,
              f"step={json.dumps(step, ensure_ascii=False)[:1200]}")
        advanced = run_engine(slot, {"行为": [{"类型": "战斗-推进", "回合详情": step.get("回合详情") or []}],
                                     "当前剧情": ""}, cmd="judge", save_dir=tmp)
        check("战斗-推进返回战斗界面并回到 READY",
              advanced.get("界面") in ("battle-ui", "battle-end-ui")
              and advanced.get("turn_state") == turn_state.READY,
              f"advanced={json.dumps(advanced, ensure_ascii=False)[:200]}")
        check("战斗界面由 engine 直出完整 Markdown",
              advanced.get("渲染模式") == "LLM" and isinstance(advanced.get("渲染文本"), str)
              and advanced.get("渲染文本") != "",
              f"advanced={json.dumps(advanced, ensure_ascii=False)[:300]}")
        # go 战斗-认输 → 战斗结束（无界面，交 judge）
        g = run_engine(slot, {"行为": [{"类型": "战斗-认输"}]}, save_dir=tmp)
        st = (g.get("战局状态") or {}).get("状态")
        check("战斗-认输结束战斗", st in ("我方认输", "我方胜", "敌方认输", "敌方胜"),
              f"st={st}")
        check("战斗 go 后进入待 judge", g.get("turn_state") == turn_state.AWAITING_JUDGE,
              f"g={json.dumps(g, ensure_ascii=False)[:200]}")
        # judge 战后处置（战斗-结束）落盘推进轮次
        j = run_engine(slot, {"行为": [{"类型": "战斗-结束"}],
                       "当前剧情": "路不平扬长而去。"}, cmd="judge", save_dir=tmp)
        check("战后处置 judge 落盘", j.get("错误") is None, f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        check("战后处置回到 READY", j.get("turn_state") == turn_state.READY, f"j={j}")
        check("战后处置推进轮次", sm.read_round(slot, tmp) == rnd0 + 1,
              f"{rnd0}→{sm.read_round(slot, tmp)}")

        # -------- 样例9：判定 CLI --------
        print("== 样例9 判定 CLI ==")
        blocked_check = run_engine(slot, {"属性": ["身法"], "判定角色": ["沈孤鸿"]}, cmd="check", save_dir=tmp)
        check("READY 状态拒绝 check", blocked_check.get("状态冲突") == "check_not_expected",
              f"blocked_check={blocked_check}")
        blocked_random = run_engine(slot, {"基础成功率": 15}, cmd="random-event", save_dir=tmp)
        check("READY 状态拒绝 random-event", blocked_random.get("状态冲突") == "random_event_not_expected",
              f"blocked_random={blocked_random}")
        run_engine(slot, {"行为": [{"类型": "交谈观察", "目标": "周遭"}]}, save_dir=tmp)
        c = run_engine(slot, {"基础成功率": 15}, cmd="random-event", save_dir=tmp)
        check("engine random-event 返回结果", c.get("结果") in ("触发", "未触发"), f"c={c}")
        check("engine random-event 带提示", "提示" in c, f"c={c}")
        check("random-event 不改变待 judge", c.get("turn_state") == turn_state.AWAITING_JUDGE, f"c={c}")
        run_engine(slot, {"行为": [], "当前剧情": "四周风平浪静。"}, cmd="judge", save_dir=tmp)

        # -------- 样例10：数据查询 CLI --------
        print("== 样例10 数据查询 CLI ==")
        q = run_engine(slot, {"类型": "角色", "名称": ["沈孤鸿"], "派生": True},
                       cmd="query", save_dir=tmp)
        check("engine query 返回存档角色", (q.get("结果") or {}).get("名称") == "沈孤鸿",
              f"q={json.dumps(q, ensure_ascii=False)[:200]}")
        s = run_engine(slot, {"目标": "丐帮"}, cmd="setting", save_dir=tmp)
        check("engine setting 返回门派设定", s.get("类型") == "门派" and s.get("门派", {}).get("名称") == "丐帮",
              f"s={json.dumps(s, ensure_ascii=False)[:200]}")
        r = run_engine(slot, {"姓名": "测试侠客", "阵营": "江湖",
                              "一级属性": {"内功": 10, "力道": 10, "身法": 10, "根骨": 10},
                              "武学偏好": "剑法"}, cmd="recommend", save_dir=tmp)
        check("engine recommend 返回三类推荐", set(r) == {"心法", "武学", "装备"},
              f"r={json.dumps(r, ensure_ascii=False)[:200]}")
        m = run_engine(slot, {"区域": "苏州"}, cmd="map-query", save_dir=tmp)
        check("engine map-query 返回场景图", m.get("区域") == "苏州" and isinstance(m.get("场景"), list),
              f"m={json.dumps(m, ensure_ascii=False)[:200]}")
        bad = run_engine(slot, {"一级属性": {"内功": 10, "力道": 10, "身法": 10, "根骨": 10},
                                "武学偏好": "枪法"}, cmd="recommend", save_dir=tmp)
        check("查询参数错误仍返回 JSON", bad.get("_rc") == 2 and "错误" in bad,
              f"bad={json.dumps(bad, ensure_ascii=False)[:200]}")

        # -------- 样例11：全部行动受阻的空数组占位 --------
        print("== 样例11 空行动数组占位 ==")
        before_no_action = sm.read_explore(slot, tmp) or {}
        no_action = run_engine(slot, {"行为": []}, save_dir=tmp)
        after_no_action = sm.read_explore(slot, tmp) or {}
        check("空行动数组零成本进入待裁定",
              no_action.get("错误") is None
              and "界面" not in no_action
              and no_action.get("turn_state") == turn_state.AWAITING_JUDGE
              and no_action.get("结算") == []
              and "GM线索提示" not in no_action
              and before_no_action == after_no_action,
              f"no_action={json.dumps(no_action, ensure_ascii=False)[:300]}")
        no_action_judge = run_engine(slot, {
            "行为": [], "当前剧情": "牢门紧锁，沈孤鸿此刻无法离开。",
        }, cmd="judge", save_dir=tmp)
        check("空行动数组后 judge 恢复 READY",
              no_action_judge.get("错误") is None
              and no_action_judge.get("turn_state") == turn_state.READY,
              f"no_action_judge={json.dumps(no_action_judge, ensure_ascii=False)[:250]}")

    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} 项：{FAILED}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
