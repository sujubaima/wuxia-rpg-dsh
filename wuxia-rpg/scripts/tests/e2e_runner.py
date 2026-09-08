#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine go/judge 端到端基本功能测试。

隔离运行：WUXIA_RPG_SAVE_DIR 指向临时目录，不污染真实存档。
覆盖十类基本功能：建档 / 门厅哨兵 / go-judge 两步式 / judge 回滚 /
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
from store import save_manager as sm

FAILED = []


def run_engine(slot, payload, cmd="go", save_dir=None):
    """subprocess 调 engine.py go/judge，stdin 传 JSON，返回解析后的 dict。"""
    payload = {"槽位": slot, **payload}
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
    """构造最小可用角色 dict（含建档所需字段）。"""
    return {
        "名称": name, "阵营": faction, "性别": "男", "年岁": 20, "武功定位": "武者",
        "品性": {"仁善": 50, "义气": 50, "胆魄": 50, "野心": 0, "底线": 50, "智计": 50,
                 "重利": 0, "守序": 50, "纵欲": 0, "信仰": 0},
        "一级属性": {"根骨": 10, "力道": 10, "身法": 10, "内功": 10},
        "极性": {"根骨": 50, "力道": 50, "身法": 50, "内功": 50},
        "铜钱": 1000, "物品": ["玉佩"],
        "武学": [], "武艺": {"搏击": 10, "剑法": 0, "刀法": 0, "长兵": 0, "奇门": 0, "暗器": 0},
        "技艺": {}, "装备": {},
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


def _copper(slot, save_dir):
    """取玩家铜钱。"""
    player = (sm.read_meta(slot, save_dir) or {}).get("角色名")
    if not player:
        return 0
    ch = dq.read_character_file(player, data_dir=sm.slot_data_dir(slot, save_dir))
    return int(ch.get("铜钱", ch.get("银两", 0)) or 0) if ch else 0


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["WUXIA_RPG_SAVE_DIR"] = tmp
        # dao.SAVE_DIR / sm.DEFAULT_SAVE_DIR 在 import 时固化，此处 patch 使本进程读取一致
        sm.DEFAULT_SAVE_DIR = tmp
        dq.SAVE_DIR = tmp

        # -------- 样例1：建档 --------
        print("== 样例1 建档 ==")
        r = run_engine(1, {"行为": [{"类型": "创建角色", "角色": char("沈孤鸿")}]}, save_dir=tmp)
        check("建档成功无错", r.get("错误") is None and "_rc" not in r, f"r={json.dumps(r, ensure_ascii=False)[:200]}")
        slot = (r.get("结算") or [{}])[0].get("新建slot")
        check("返回新建slot", slot is not None, f"r={json.dumps(r, ensure_ascii=False)[:200]}")
        check("建档带落点", (r.get("结算") or [{}])[0].get("落点"), f"r={json.dumps(r, ensure_ascii=False)[:200]}")

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
        g = run_engine(slot, {"行为": [{"类型": "交谈观察"}]}, save_dir=tmp)
        check("go 交谈观察无界面（需调 judge）", "界面" not in g, f"g={list(g.keys())}")
        j = run_engine(slot, {"行为": [
            {"类型": "物品", "操作": "减", "角色": "沈孤鸿", "名": "玉佩", "数量": 1},
        ], "当前剧情": "沈孤鸿把玉佩收进怀里。"}, cmd="judge", save_dir=tmp)
        check("judge 正常落盘无错", j.get("错误") is None, f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        check("judge 返回 exploration-ui", j.get("界面") == "exploration-ui", f"界面={j.get('界面')}")
        check("落盘后玩家无玉佩", _has_item(slot, "玉佩", tmp, expected=False))

        # -------- 样例4：judge 回滚 --------
        print("== 样例4 judge 回滚 ==")
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
        j = run_engine(slot, {"行为": [
            {"类型": "写角色", "角色": empty_npc},
        ], "当前剧情": "无艺客出现在路旁。"}, cmd="judge", save_dir=tmp)
        check("judge 拒绝武学为空的角色",
              j.get("错误") is not None and "武学不能为空" in str(j.get("错误", "")),
              f"错误={j.get('错误')}")
        check("武学为空的角色不落盘",
              dq.read_character_file("无艺客", data_dir=sm.slot_data_dir(slot, tmp)) is None)

        skilled_npc = char("有艺客")
        skilled_npc["武学"] = [{"名称": "百缠手", "等级": 1}]
        j = run_engine(slot, {"行为": [
            {"类型": "写角色", "角色": skilled_npc},
        ], "当前剧情": "有艺客出现在路旁。"}, cmd="judge", save_dir=tmp)
        check("judge 接受武学非空的角色", j.get("错误") is None,
              f"错误={j.get('错误')}")
        check("武学非空的角色正常落盘",
              dq.read_character_file("有艺客", data_dir=sm.slot_data_dir(slot, tmp)) is not None)

        # -------- 样例5：judge 顶层校验 --------
        print("== 样例5 judge 顶层校验 ==")
        j = run_engine(slot, {"行为": [], "当前剧情": "x", "非法字段": 1}, cmd="judge", save_dir=tmp)
        check("judge 拒绝非预期顶层字段", j.get("错误") is not None and "非预期字段" in str(j.get("错误", "")),
              f"错误={j.get('错误')}")
        check("顶层校验属 gm_error", j.get("gm_error") is True or "非法" in str(j.get("错误", "")),
              f"resp={json.dumps(j, ensure_ascii=False)[:200]}")

        # -------- 样例6：场景登记校验 --------
        print("== 样例6 场景登记校验 ==")
        j = run_engine(slot, {"行为": [{
            "类型": "登记场景", "区域": "回归测试区", "场景": "回环庭",
            "方位出口": {"北": "回环庭"},
        }], "当前剧情": "测试场景登记。"}, cmd="judge", save_dir=tmp)
        check("judge 拒绝场景出口指向自身",
              j.get("错误") is not None and "出口不能指向自身" in str(j.get("错误", "")),
              f"错误={j.get('错误')}")
        overlay = sm.read_map_overlay(slot, tmp)
        check("自环登记失败后不落盘", "回环庭" not in (overlay.get("回归测试区") or {}),
              f"overlay={overlay.get('回归测试区')}")
        j = run_engine(slot, {"行为": [{
            "类型": "登记场景", "区域": "回归测试区", "场景": "甲地",
            "方位出口": {"北": "乙地"},
        }], "当前剧情": "测试正常场景登记。"}, cmd="judge", save_dir=tmp)
        check("judge 接受正常场景连接", j.get("错误") is None,
              f"错误={j.get('错误')}")
        overlay = sm.read_map_overlay(slot, tmp).get("回归测试区") or {}
        check("正常连接自动补反向出口",
              overlay.get("甲地", {}).get("北") == "乙地"
              and overlay.get("乙地", {}).get("南") == "甲地",
              f"overlay={overlay}")

        # -------- 样例7：查询类带界面 --------
        print("== 样例7 查询类带界面 ==")
        g = run_engine(slot, {"行为": [{"类型": "角色信息", "角色": "沈孤鸿"}]}, save_dir=tmp)
        check("角色信息带界面", g.get("界面") in ("character-ui", "exploration-ui"), f"界面={g.get('界面')}")
        g = run_engine(slot, {"行为": [{"类型": "查看背包", "角色": "沈孤鸿"}]}, save_dir=tmp)
        check("查看背包带界面", g.get("界面") in ("bag-ui", "exploration-ui"), f"界面={g.get('界面')}")

        # -------- 样例8：战斗流程 --------
        print("== 样例8 战斗流程 ==")
        # 敌人用基线已有角色（避免重名校验）；战斗-开始为 judge 专属 action
        enemy = "路不平"
        rnd0 = sm.read_round(slot, tmp)
        j = run_engine(slot, {"行为": [{"类型": "战斗-开始", "我方": ["沈孤鸿"], "敌方": [enemy],
                                       "允许逃跑": True, "操控方式": "玩家角色"}],
                           "当前剧情": "路不平拦路！"}, cmd="judge", save_dir=tmp)
        check("战斗-开始被接受无错", j.get("错误") is None and "_rc" not in j,
              f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        check("战斗-开始不推进轮次", sm.read_round(slot, tmp) == rnd0,
              f"{rnd0}→{sm.read_round(slot, tmp)}")
        # 战斗中 返回游戏 拒绝（战斗临时文件存在时）
        rg = run_engine(slot, {"行为": [{"类型": "返回游戏"}]}, save_dir=tmp)
        check("战斗中返回游戏拒绝", rg.get("提示") is not None or rg.get("错误") is not None,
              f"rg={json.dumps(rg, ensure_ascii=False)[:150]}")
        # go 战斗-认输 → 战斗结束（无界面，交 judge）
        g = run_engine(slot, {"行为": [{"类型": "战斗-认输"}]}, save_dir=tmp)
        st = (g.get("战局状态") or {}).get("状态")
        check("战斗-认输结束战斗", st in ("我方认输", "我方胜", "敌方认输", "敌方胜"),
              f"st={st}")
        # judge 战后处置（战斗-结束）落盘推进轮次
        j = run_engine(slot, {"行为": [{"类型": "战斗-结束"}],
                       "当前剧情": "路不平扬长而去。"}, cmd="judge", save_dir=tmp)
        check("战后处置 judge 落盘", j.get("错误") is None, f"resp={json.dumps(j, ensure_ascii=False)[:200]}")
        check("战后处置推进轮次", sm.read_round(slot, tmp) == rnd0 + 1,
              f"{rnd0}→{sm.read_round(slot, tmp)}")

        # -------- 样例9：判定 CLI --------
        print("== 样例9 判定 CLI ==")
        c = run_engine(slot, {"基础成功率": 15}, cmd="random-event", save_dir=tmp)
        check("engine random-event 返回结果", c.get("结果") in ("触发", "未触发"), f"c={c}")
        check("engine random-event 带提示", "提示" in c, f"c={c}")

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

    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} 项：{FAILED}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
