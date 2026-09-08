#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用战斗入口：任意参战角色、任意阵营分组、有无玩家参与，统一完成战斗 + 三层渲染。

模式由 --player 决定：
  - 不带 --player  → 纯 AI 对战，一条命令跑完整场并输出三层战报
  - 带 --player    → 玩家操控交互战，分 start / go / info 三个子命令推进
  - stats 子命令   → 不进战斗，输出角色派生后的完整属性（基础派生 + 武学反哺 + 装备加成）

对战必须用 --teams 显式指定分组（分号隔开队伍，逗号隔开队内成员，可选「标签:」命名），
不再按角色 JSON 的「阵营」字段默认分队。支持任意人数与任意阵营数，与输入顺序无关。

`--允许逃跑 <true|false>` 必填：GM 战前据剧情人设判定本场是否允许逃跑（true/false、是/否、1/0）。

用法：
  # 纯 AI（观战）——对战必须 --teams 指定分组
  python3 battle.py --允许逃跑 false --teams 朱如碧;和悦 朱如碧 和悦
  python3 battle.py --seed 7 --允许逃跑 true --teams 甲:陈挺之,骆逸;乙:穆双清 陈挺之 骆逸 穆双清

  # 分队格式：分号隔开队伍，逗号隔开队内成员；可选「标签:」前缀命名队伍
  python3 battle.py --允许逃跑 false --teams 穆双清,余绮;和悦,陈挺之 穆双清 余绮 和悦 陈挺之
  python3 battle.py --teams 九溪:穆双清,余绮;北辰:和悦,陈挺之 穆双清 余绮 和悦 陈挺之

  # 玩家操控
  python3 battle.py start --player 陈挺之 --teams 朱如碧,余绮;和悦,陈挺之 朱如碧 和悦 余绮 陈挺之
  python3 battle.py go '武学 天道三垣剑 朱如碧'
  python3 battle.py go '休息'
  python3 battle.py info            # 查看人物信息（不消耗回合）

  # 派生属性查询（不进战斗，与战斗同源）
  python3 battle.py stats 骆逸
  python3 battle.py stats 骆逸 陈挺之

本模块同时是三层战报渲染器的实现所在：
  - render_results(results, skills_db, start_idx=1, with_header=False, teams=None)
    把 auto_advance 返回的「结算列表」直出为三层文本，纯 AI / 玩家操控通用。
"""
import json
import os
import sys
import random

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from combat import battle_engine as be
from common import dao as dq
from common.json_io import JsonMissingError, atomic_write_json, read_json
from store import battle_runtime as br
from store.save_manager import slot_data_dir

DATA_DIR = os.path.join(HERE, "..", "assets", "data")
CHAR_DIR = os.path.join(DATA_DIR, "characters")

STATE_FILE = br.STATE_FILENAME
META_FILE = br.META_FILENAME
REPORT_FILE = br.REPORT_FILENAME

DEFAULT_NAMES = ["朱如碧", "和悦", "余绮", "陈挺之"]
DEFAULT_PLAYER = "陈挺之"

# 运行时由 meta 解析；交互层各函数引用此全局
PLAYER = DEFAULT_PLAYER


# ========== 角色构建 ==========
CN_NUMS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def parse_teams(spec):
    """解析自定义分队说明，返回 {角色名: 队伍标签}。

    格式：分号隔开各队伍，逗号隔开队内成员。
    每段可用「标签:」前缀为队伍命名，缺省则合成「队伍一/二/…」。
    例：'穆双清,余绮;和悦,陈挺之' 或 '九溪:穆双清,余绮;北辰:和悦,陈挺之'
    """
    faction_map = {}
    for idx, seg in enumerate(spec.split(";")):
        seg = seg.strip()
        if not seg:
            continue
        label = None
        if ":" in seg:
            label, seg = seg.split(":", 1)
            label = label.strip()
            seg = seg.strip()
        if not label:
            label = f"队伍{CN_NUMS[idx]}" if idx < len(CN_NUMS) else f"队伍{idx + 1}"
        for name in seg.split(","):
            name = name.strip()
            if name:
                faction_map[name] = label
    return faction_map


def load_char(name):
    char = dq.get("角色", name)
    if char is None:
        raise FileNotFoundError(f"未找到角色【{name}】（经 dao 未找到）")
    return char


def build_chars(names, faction_map=None):
    """从预设库构建参战角色对象（仅保留引擎所需字段，二级属性/气血/内力交引擎派生）。

    阵营（队伍）一律由 faction_map 指定，不再读取角色 JSON 的「阵营」字段——对战分组
    必须显式给出（见 main 的 --teams），杜绝按门派默认分队。faction_map 未覆盖的角色
    以其名为阵营（仅供单角色派生 derive_char 等非对战场景，每人独成一队避免误判同队）。
    """
    keep = ["名称", "一级属性", "极性", "武艺", "技艺", "武学", "装备"]
    chars = []
    for n in names:
        c = load_char(n)
        cc = {k: c[k] for k in keep}
        cc["物品"] = list(c.get("物品", []))  # 物品栏（消耗实际扣减处），缺省空
        # 运转心法为可选字段，未设定时不写入
        if c.get("运转心法"):
            cc["运转心法"] = c["运转心法"]
        # 携带技能为可选字段（配置上场的主动武学，至多4门）；未设定时不写入，由引擎回退全部已习得
        if "携带技能" in c:
            cc["携带技能"] = c["携带技能"]
        # 携带物品为可选字段（配置上场的消耗品种类，至多4类）；未设定时不写入，由引擎回退物品栏消耗品
        if "携带物品" in c:
            cc["携带物品"] = c["携带物品"]
        # 携带当前气血/内力（若文件已持久化）：使战后带回探索的残血/残内力在下一场战斗延续，
        # 而非每战重置为上限。未持久化（如预设 NPC）则不下发，由引擎 setdefault 取上限。
        for opt in ("气血", "内力"):
            if opt in c:
                cc[opt] = c[opt]
        cc["阵营"] = faction_map[n] if (faction_map and n in faction_map) else n
        cc["充能"] = 0
        cc["充能速率"] = 0
        cc["状态效果"] = []
        cc["冷却"] = {}
        # 单场物品可用次数上限：min(开战时背包该物品数, 2)；使用时递减，归零即不可用
        inv0 = cc["物品"]
        cc["物品可用次数"] = {nm: min(inv0.count(nm), 2) for nm in set(inv0)} if isinstance(inv0, list) else {}
        chars.append(cc)
    return chars


def derive_char(name):
    """构建单角色并完成与战斗同源的属性派生，返回派生后的角色 dict。

    派生内核（基础派生 + 武学反哺 + 装备加成）已下沉至 dao.derive_character，
    本函数仅负责按名加载角色并委托，使 save_manager 等无需 import battle 即可复刻派生。
    结果与战斗内核一致，供 stats 子命令与大世界「查看人物」取用，避免手算。
    """
    skills_db = be.load_skills()
    characters_db = be.load_characters()
    c = build_chars([name])[0]
    return dq.derive_character(c, characters_db, skills_db)


# ========== 三层战报渲染器 ==========
ATTACK_VERBS = ["刺向", "劈向", "扫向", "直取", "横斩向", "点向"]


def moves_of(skill):
    """武学的招式名列表（取「招式」字段，2~3 个）。"""
    return list(skill.get("招式") or [])


def bonus_clause_of(res):
    """由结算字典构造增伤小注：无增伤返回空串；有则附来源状态名（如 增伤×1.2·【西子捧心】）。"""
    mult = res.get("增伤倍率")
    if not mult:
        return ""
    src = res.get("增伤来源") or []
    if src:
        names = "、".join(f"【{s['状态']}】" for s in src)
        return f"（增伤×{mult}·{names}）"
    return f"（增伤×{mult}）"


def followup_clause_of(res):
    """雷印追击小注：目标雷印叠层触发后，复用本次伤害数值再落一次等量伤害。
    res 为单目标结算（武学单体/全体逐目标 tr）。"""
    fu = res.get("追击结算")
    if not fu:
        return ""
    parts = []
    for g in fu:
        t = g["目标"]
        defeat = "，气绝倒地" if g.get("击败") else ""
        if g.get("霸体抵挡"):
            parts.append(f"雷印引爆、{t}受击被【{g['霸体抵挡']['名称']}】所挡")
        else:
            life = qiangming_clause_of(g)
            life_clause = f"，{life}" if life else ""
            parts.append(f"雷印引爆、{t}再受{g['伤害']}点伤害{life_clause}{defeat}")
    return "，" + "；".join(parts)


def reflect_rows_of(res):
    """统一返回反伤结算列表。"""
    rows = res.get("反伤结算") or []
    return rows if isinstance(rows, list) else [rows]


def reflect_clause_of(res):
    """反伤小注：显示返还伤害及防护、保命、击败结果。"""
    parts = []
    for row in reflect_rows_of(res):
        target = row.get("目标", "")
        if row.get("霸体抵挡"):
            parts.append(f"【反伤】震返之力被{target}【{row['霸体抵挡']['名称']}】所挡")
            continue
        life = qiangming_clause_of(row)
        life_clause = f"，{life}" if life else ""
        defeat = "，气绝倒地" if row.get("击败") else ""
        parts.append(f"【反伤】震返{row.get('伤害', 0)}点伤害予{target}{life_clause}{defeat}")
    return ("，" + "；".join(parts)) if parts else ""


def cooldown_clause_of(res):
    """技能冷却变化小注。"""
    parts = []
    for row in res.get("冷却变化", []):
        target, skill = row.get("目标", ""), row.get("武学", "")
        if row.get("新增冷却"):
            parts.append(f"{target}【{skill}】进入1回合冷却")
        else:
            parts.append(f"{target}【{skill}】冷却延长1回合")
    return ("，" + "；".join(parts)) if parts else ""


def status_transfer_clause_of(res):
    """负面状态转移小注。"""
    parts = []
    for row in res.get("状态转移", []):
        name = row.get("名称", "")
        target = row.get("转移目标", "")
        if name and target:
            parts.append(f"将自身【{name}】转予{target}")
    return ("，" + "；".join(parts)) if parts else ""


def guard_clause_of(res):
    """霸体抵挡小注：携带者以霸体无效化本次技能伤害并消耗一层。
    res 为单目标结算（武学单体/全体逐目标 tr）。无抵挡返回空串。"""
    g = res.get("霸体抵挡")
    if not g:
        return ""
    return f"伤害尽化虚无，为【{g.get('名称', '霸体')}】所挡"


def qiangming_clause_of(res):
    """强命触发小注：列出本次行动中锁住1点气血并消耗一层的角色。"""
    guards = res.get("强命保命") or []
    if isinstance(guards, dict):
        guards = [guards]
    parts = []
    for g in guards:
        target = g.get("目标", "")
        name = g.get("名称", "强命")
        parts.append(f"{target}由【{name}】护住最后1点气血")
    return "，".join(parts)


def worsen_clause_of(res):
    """加剧负面小注：技能特效（如椎心八法）令目标非长效负面状态持续时间翻倍。
    res 为单目标结算（武学单体/全体逐目标 tr）。"""
    worsen = res.get("加剧负面")
    if not worsen:
        return ""
    names = "、".join(f"【{g['名称']}】" for g in worsen)
    return f"，{names}诸般厄患皆延一筹"


def gain_src_clause(g, actor):
    """施加状态附注：格式（来自{施加者}【{来源}】）；来源缺则空。"""
    src = g.get("来源")
    if not src:
        return ""
    applier = g.get("施加者")
    if applier:
        return f"（来自{applier}【{src}】）"
    return f"（来自【{src}】）"


def counter_clause_of(r):
    """第一层反制小注：汇总本回合时序变化事件中令攻方出招延后(变化为负)的来源，作'【XX】反制致出招延后'。
    仅由被攻击反制(on_target_confirmed，带 来源名称)发起；技能特效的时序调整(无来源)不计入此小注。"""
    names = []
    for ev in r.get("时序变化", []):
        if ev.get("变化", 0) >= 0 or not ev.get("来源名称"):
            continue
        n = ev["来源名称"]
        if n not in names:
            names.append(n)
    for tr in r.get("目标结算", []):
        for ev in tr.get("时序变化", []):
            if ev.get("变化", 0) >= 0 or not ev.get("来源名称"):
                continue
            n = ev.get("来源名称")
            if n and n not in names:
                names.append(n)
    if not names:
        return ""
    return f"，{'、'.join(f'【{n}】' for n in names)}反制致出招延后"


def cleanse_clause_of(r):
    """第一层自身净化小注：汇总本回合移除的自身非长效负面状态，作'涤荡周身、散去XX之厄'。
    由技能特效 on_target_resolved（如鸿蒙刀法）写入顶层 移除负面 字段。"""
    removed = r.get("移除负面", [])
    if not removed:
        return ""
    names = [rm["名称"] for rm in removed if rm.get("名称")]
    if not names:
        return ""
    return f"，涤荡周身、散去{'、'.join(names)}之厄"


def render_turn(idx, r, skills_db):
    """渲染单回合三层文本。idx 为回合序（从1起）。"""
    actor = r["行动者"]
    cmd = r["指令"]
    expire = [e["名称"] for e in r.get("状态失效", [])]
    expire_clause = "".join(f"，【{n}】状态消退" for n in expire)

    # 持续伤害（外伤等流血/中毒，于携带者回合结束触发）：第一层点名来源与总损血，第三层合并气血变化
    dots = r.get("持续伤害", [])
    if dots:
        n = len(dots)
        layer = f"（{n}层）" if n > 1 else ""
        src = dots[0].get("来源", "外伤")
        # 按实际落账方向陈述（【七星逆脉】携带者的流血改耗内力）
        hp_loss = sum(d["原值"] - d["新值"] for d in dots)
        mp_loss = sum(d.get("改扣内力", 0) for d in dots)
        loss_parts = ([f"再损{hp_loss}点气血"] if hp_loss else []) + ([f"耗损{mp_loss}点内力"] if mp_loss else [])
        dot_clause = f"，【{src}】持续流血{layer}、" + "、".join(loss_parts) if loss_parts else ""
        if r.get("持续伤害击败"):
            dot_clause += f"，{actor}气血枯竭、气绝倒地"
    else:
        dot_clause = ""

    # 持续恢复（回春等回血，于携带者回合结束触发）：第一层点名来源与总回血，第三层合并气血变化
    hots = r.get("持续恢复", [])
    if hots:
        total = sum(h["数值"] for h in hots)
        n = len(hots)
        layer = f"（{n}层）" if n > 1 else ""
        src = hots[0].get("来源", "回春")
        hot_clause = f"，【{src}】药力续生{layer}、恢复{total}点气血"
    else:
        hot_clause = ""

    # 持续恢复内力（小周天等回内，于携带者回合结束触发）：第一层并入 hot_clause，第三层合并内力变化
    mp_hots = r.get("持续恢复内力", [])
    if mp_hots:
        total_mp = sum(h["数值"] for h in mp_hots)
        src_mp = mp_hots[0].get("来源", "小周天")
        mp_hot_clause = f"，【{src_mp}】运转、回复{total_mp}点内力"
    else:
        mp_hot_clause = ""

    # ---- 第一层：战局描述 ----
    if cmd == "逃跑":
        if r.get("逃跑成功"):
            layer1 = f"{actor}见势不妙、抽身便走，几步之间已遁出圈外，脱身而去。"
        else:
            layer1 = f"{actor}虚晃一招欲抽身遁走，却被缠住脱身不得，反倒露出破绽。"
    elif cmd == "认输":
        layer1 = f"{actor}弃刃罢手、低头认负，这场较量到此为止。"
    elif cmd == "休息":
        hp = r.get("恢复气血", 0)
        mp = r.get("恢复内力", 0)
        rest_src = ""
        if r.get("恢复改写来源"):
            names = "、".join(f"【{s['状态']}】" for s in r["恢复改写来源"])
            rest_src = f"（受{names}所制）"
        layer1 = f"{actor}敛剑调息，恢复{hp}点气血{rest_src}、{mp}点内力{expire_clause}。"
    elif cmd == "无法行动":
        layer1 = f"{actor}{r.get('原因', '')}，无法行动{expire_clause}。"
    elif cmd == "物品":
        if r.get("物品子类型") == "道具":
            gains = r.get("施加状态", [])
            if gains:
                st = "、".join(f"【{g['名称']}】" for g in gains)
                layer1 = f"{actor}扬手洒出【{r.get('物品', '')}】扑向{r.get('目标', '')}，令其陷入{st}{expire_clause}。"
            elif r.get("时序变化"):
                layer1 = f"{actor}掷出【{r.get('物品', '')}】，轰然炸响震得{r.get('目标', '')}阵脚大乱、出招延后{expire_clause}。"
            else:
                layer1 = f"{actor}对{r.get('目标', '')}使用【{r.get('物品', '')}】{expire_clause}。"
        else:
            gains = r.get("施加状态", [])
            purged = r.get("净化状态")
            weakened = r.get("削减状态")
            extended = r.get("延长状态")
            if gains:
                st = "、".join(f"【{g['名称']}】" for g in gains)
                layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，药力渐生、得其{st}{expire_clause}。"
            elif purged is not None:
                if purged:
                    st = "、".join(f"【{g['名称']}】" for g in purged)
                    layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，神思一清、散去{st}之厄{expire_clause}。"
                else:
                    layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，神思一清，然身上并无时下之厄可散{expire_clause}。"
            elif weakened is not None:
                if weakened:
                    names = "、".join(f"【{g['名称']}】" for g in weakened)
                    layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，药性中和、{names}诸般厄患皆减一筹{expire_clause}。"
                else:
                    layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，药性中和，然身上并无时下之厄{expire_clause}。"
            elif extended is not None:
                if extended:
                    names = "、".join(f"【{g['名称']}】" for g in extended)
                    layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，药力相生、{names}诸般助力皆延一筹{expire_clause}。"
                else:
                    layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，药力相生，然身上并无时下之助{expire_clause}。"
            else:
                hp_h = r.get('恢复气血', 0)
                mp_h = r.get('恢复内力', 0)
                if mp_h and not hp_h:
                    layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，回复{mp_h}点内力{expire_clause}。"
                else:
                    layer1 = f"{actor}取出【{r.get('物品', '')}】予{r.get('目标', '')}服下，回复{hp_h}点气血{expire_clause}。"
    else:
        skill_name = r.get("技能", "")
        target = r.get("目标", "")
        skill = skills_db.get(skill_name, {})
        moves = moves_of(skill)
        move = moves[(idx - 1) % len(moves)] if moves else ""
        move_str = f"一式「{move}」" if move else ""
        verb = ATTACK_VERBS[idx % len(ATTACK_VERBS)]

        gains = r.get("施加状态", [])
        gain_clause = ""
        for g in gains:
            who = "自身" if g["目标"] == actor else g["目标"]
            gain_clause += f"，{who}获得【{g['名称']}】状态{gain_src_clause(g, actor)}"
        counter_clause = counter_clause_of(r)
        cleanse_clause = cleanse_clause_of(r)

        if r.get("目标结算"):  # 敌方全体
            head = (f"{actor}【{skill_name}】{move_str}剑势如风、横扫敌方全体"
                    f"{counter_clause}{cleanse_clause}{expire_clause}。")
            sub_lines = []
            aoe_gains = []
            for tr in r["目标结算"]:
                t = tr["目标"]
                if tr.get("闪避"):
                    sub_lines.append(f"  · {t}闪身避开。")
                    continue
                crit_clause = f"暴击要害（{tr.get('暴击倍率', '')}倍），" if tr.get("暴击") else ""
                dmg = tr.get("伤害", 0)
                mp_dmg = tr.get("内力伤害", 0)
                drain_clause = f"，另化{mp_dmg}点剑气透入经脉、伤其内力" if mp_dmg else ""
                defeat_clause = f"，{t}气绝倒地" if tr.get("击败") else ""
                bonus_clause = bonus_clause_of(tr)
                worsen_clause = worsen_clause_of(tr)
                followup_clause = followup_clause_of(tr)
                reflect_clause = reflect_clause_of(tr)
                cooldown_clause = cooldown_clause_of(tr)
                transfer_clause = status_transfer_clause_of(tr)
                guard_clause = guard_clause_of(tr)
                life = qiangming_clause_of(tr)
                life_clause = f"，{life}" if life else ""
                dmg_clause = guard_clause if guard_clause else f"造成{dmg}点伤害"
                sub_lines.append(f"  · {t}：{crit_clause}{dmg_clause}{bonus_clause}{drain_clause}{worsen_clause}{followup_clause}{reflect_clause}{cooldown_clause}{transfer_clause}{life_clause}{defeat_clause}。")
                for g in tr.get("施加状态", []):
                    who = "自身" if g["目标"] == actor else g["目标"]
                    aoe_gains.append(f"{who}获得【{g['名称']}】状态{gain_src_clause(g, actor)}")
            gain_line = ("；".join(aoe_gains) + "。") if aoe_gains else ""
            layer1 = head + "\n" + "\n".join(sub_lines) + (("\n" + gain_line) if gain_line else "")
        elif r.get("闪避"):
            layer1 = (f"{actor}【{skill_name}】{move_str}{verb}{target}，"
                      f"{target}闪身避开{gain_clause}{expire_clause}。")
        else:
            dmg = r.get("伤害", 0)
            crit_clause = f"暴击要害（{r.get('暴击倍率', '')}倍），" if r.get("暴击") else ""
            mp_dmg = r.get("内力伤害", 0)
            drain_clause = f"，另化{mp_dmg}点剑气透入经脉、伤其内力" if mp_dmg else ""
            defeat_clause = f"{target}气绝倒地。" if r.get("击败") else ""
            bonus_clause = bonus_clause_of(r)
            worsen_clause = worsen_clause_of(r)
            followup_clause = followup_clause_of(r)
            reflect_clause = reflect_clause_of(r)
            cooldown_clause = cooldown_clause_of(r)
            transfer_clause = status_transfer_clause_of(r)
            guard_clause = guard_clause_of(r)
            dmg_clause = guard_clause if guard_clause else f"造成{dmg}点伤害"
            layer1 = (f"{actor}【{skill_name}】{move_str}{verb}{target}，"
                      f"{crit_clause}{dmg_clause}{bonus_clause}{drain_clause}{gain_clause}{counter_clause}{cleanse_clause}{worsen_clause}{followup_clause}{reflect_clause}{cooldown_clause}{transfer_clause}{expire_clause}。"
                      + defeat_clause)

    # 持续伤害/持续恢复与强命触发描述并入第一层首句（作用于行动者或单体目标）
    life = qiangming_clause_of(r)
    life_clause = f"，{life}" if life else ""
    if dot_clause or hot_clause or mp_hot_clause or life_clause:
        l1 = layer1.split("\n")
        l1[0] = l1[0].rstrip("。") + dot_clause + hot_clause + mp_hot_clause + life_clause + "。"
        layer1 = "\n".join(l1)

    # ---- 第三层：数值与状态变化（箭头报告） ----
    chg = {}

    def ensure(n):
        return chg.setdefault(n, {"气血": None, "内力": None, "gain": [], "lose": [], "减衰": [], "延长": [], "时序": None})

    def merge_reflect(row):
        target = row.get("目标")
        if not target:
            return
        entry = ensure(target)
        if row.get("原值") != row.get("新值"):
            entry["气血"] = ((entry["气血"][0] if entry["气血"] else row["原值"]),
                             row["新值"])
        if row.get("内力原值") != row.get("内力新值"):
            entry["内力"] = ((entry["内力"][0] if entry["内力"] else row["内力原值"]),
                             row["内力新值"])
        guard = row.get("霸体抵挡")
        if guard and guard.get("名称"):
            ensure(guard["目标"])["lose"].append(guard["名称"])
        for marker in row.get("强命保命", []):
            ensure(marker["目标"])["lose"].append(marker["名称"])

    def merge_transfer(row):
        source = row.get("来源目标")
        target = row.get("转移目标")
        name = row.get("名称")
        if not source or not target or not name:
            return
        ensure(source)["lose"].append(name)
        ensure(target)["gain"].append((name, row.get("持续时间", 0)))

    if cmd == "武学":
        mp = r.get("行动者内力变化")
        if mp and mp["原值"] != mp["新值"]:
            ensure(actor)["内力"] = (mp["原值"], mp["新值"])
        hp_a = r.get("行动者气血变化")
        if hp_a and hp_a["原值"] != hp_a["新值"]:
            ensure(actor)["气血"] = (hp_a["原值"], hp_a["新值"])
        if r.get("目标结算"):  # 敌方全体：逐目标汇总气血/内力变化与状态
            for tr in r["目标结算"]:
                t = tr["目标"]
                hp = tr.get("目标气血变化")
                if hp and hp["原值"] != hp["新值"]:
                    ensure(t)["气血"] = (hp["原值"], hp["新值"])
                tmp = tr.get("目标内力变化")
                if tmp and tmp["原值"] != tmp["新值"]:
                    ensure(t)["内力"] = (tmp["原值"], tmp["新值"])
                for g in tr.get("施加状态", []):
                    ensure(g["目标"])["gain"].append((g["名称"], g["持续时间"]))
                for g in tr.get("加剧负面", []):
                    ensure(g["目标"])["延长"].append((g["名称"], g["原剩余"], g["新剩余"]))
                # 涤荡目标增益（技能特效 on_target_resolved 移除命中目标非长效正向，如夜来风雨势）：入目标 lose
                for g in tr.get("移除增益", []):
                    if g.get("名称"):
                        ensure(g["目标"])["lose"].append(g["名称"])
                # 霸体抵挡：携带者消耗一层霸体无效化技能伤害，入目标 lose
                gd = tr.get("霸体抵挡")
                if gd and gd.get("名称"):
                    ensure(gd["目标"])["lose"].append(gd["名称"])
                for qg in tr.get("强命保命", []):
                    ensure(qg["目标"])["lose"].append(qg["名称"])
                # 雷印追击：追击在主攻之后，气血最终值以追击后为准（合并覆盖主攻新值）
                for g in tr.get("追击结算", []):
                    if g.get("原值") != g.get("新值"):
                        e = ensure(g["目标"])
                        if e["气血"]:
                            e["气血"] = (e["气血"][0], g["新值"])
                        else:
                            e["气血"] = (g["原值"], g["新值"])
                    for qg in g.get("强命保命", []):
                        ensure(qg["目标"])["lose"].append(qg["名称"])
                for reflected in reflect_rows_of(tr):
                    merge_reflect(reflected)
                for moved in tr.get("状态转移", []):
                    merge_transfer(moved)
            # 自身效果提顶后（AOE on_target_resolved 自施类，如缥缈）：顶层 施加状态 的自施条目入 gain
            for g in r.get("施加状态", []):
                if g.get("目标") == actor:
                    ensure(actor)["gain"].append((g["名称"], g.get("持续时间")))
        else:
            hp = r.get("目标气血变化")
            if hp and hp["原值"] != hp["新值"]:
                ensure(r["目标"])["气血"] = (hp["原值"], hp["新值"])
            tmp = r.get("目标内力变化")
            if tmp and tmp["原值"] != tmp["新值"]:
                ensure(r["目标"])["内力"] = (tmp["原值"], tmp["新值"])
            for g in r.get("施加状态", []):
                ensure(g["目标"])["gain"].append((g["名称"], g["持续时间"]))
            for g in r.get("加剧负面", []):
                ensure(g["目标"])["延长"].append((g["名称"], g["原剩余"], g["新剩余"]))
            # 涤荡目标增益（技能特效 on_target_resolved 移除命中目标非长效正向，如夜来风雨势）：入目标 lose
            for g in r.get("移除增益", []):
                if g.get("名称"):
                    ensure(g["目标"])["lose"].append(g["名称"])
            # 霸体抵挡：携带者消耗一层霸体无效化技能伤害，入目标 lose
            gd = r.get("霸体抵挡")
            if gd and gd.get("名称"):
                ensure(gd["目标"])["lose"].append(gd["名称"])
            # 雷印追击：追击在主攻之后，气血最终值以追击后为准（合并覆盖主攻新值）
            for g in r.get("追击结算", []):
                if g.get("原值") != g.get("新值"):
                    e = ensure(g["目标"])
                    if e["气血"]:
                        e["气血"] = (e["气血"][0], g["新值"])
                    else:
                        e["气血"] = (g["原值"], g["新值"])
                for qg in g.get("强命保命", []):
                    ensure(qg["目标"])["lose"].append(qg["名称"])
            for reflected in reflect_rows_of(r):
                merge_reflect(reflected)
            for moved in r.get("状态转移", []):
                merge_transfer(moved)
        # 自身净化（技能特效 on_target_resolved 移除自身非长效负面，如鸿蒙刀法）：入行动者 lose
        for rm in r.get("移除负面", []):
            if rm.get("名称"):
                ensure(actor)["lose"].append(rm["名称"])
    elif cmd == "休息":
        hp = r.get("气血变化")
        mp = r.get("内力变化")
        a = ensure(actor)
        if hp:
            a["气血"] = (hp["原值"], hp["新值"])
        if mp:
            a["内力"] = (mp["原值"], mp["新值"])
    elif cmd == "物品":
        hp = r.get("目标气血变化")
        if hp and hp["原值"] != hp["新值"]:
            ensure(r["目标"])["气血"] = (hp["原值"], hp["新值"])
        mp = r.get("目标内力变化")
        if mp and mp["原值"] != mp["新值"]:
            ensure(r["目标"])["内力"] = (mp["原值"], mp["新值"])
        for g in r.get("施加状态", []):
            ensure(g["目标"])["gain"].append((g["名称"], g["持续时间"]))
        for g in r.get("净化状态", []):
            ensure(g["目标"])["lose"].append(g["名称"])
        for g in r.get("削减状态", []):
            if g.get("失效"):
                ensure(g["目标"])["lose"].append(g["名称"])
            else:
                ensure(g["目标"])["减衰"].append((g["名称"], g["原剩余"], g["新剩余"]))
        for g in r.get("延长状态", []):
            ensure(g["目标"])["延长"].append((g["名称"], g["原剩余"], g["新剩余"]))
        for ev in r.get("时序变化", []):
            e = ensure(ev.get("目标") or r.get("目标"))
            e["时序"] = (e["时序"] or 0) + ev.get("变化", 0)
    # 主结算、DOT或技能气血消耗触发强命：消耗的一层入对应角色 lose。
    for qg in r.get("强命保命", []):
        ensure(qg["目标"])["lose"].append(qg["名称"])
    for n in expire:
        ensure(actor)["lose"].append(n)

    # 持续伤害：合并到携带者（行动者）的气血变化（多段叠加取首段原值→末段新值）
    for d in r.get("持续伤害", []):
        e = ensure(d["目标"])
        if e["气血"]:
            e["气血"] = (e["气血"][0], d["新值"])
        elif d["原值"] != d["新值"]:
            e["气血"] = (d["原值"], d["新值"])
        # 互换改扣内力（【七星逆脉】）：合并内力箭头
        if d.get("内力原值") is not None:
            if e["内力"]:
                e["内力"] = (e["内力"][0], d["内力新值"])
            elif d["内力原值"] != d["内力新值"]:
                e["内力"] = (d["内力原值"], d["内力新值"])

    # 持续恢复：同上合并到携带者气血变化
    for h in r.get("持续恢复", []):
        e = ensure(h["目标"])
        if e["气血"]:
            e["气血"] = (e["气血"][0], h["新值"])
        else:
            e["气血"] = (h["原值"], h["新值"])

    # 持续恢复内力：合并到携带者内力变化
    for h in r.get("持续恢复内力", []):
        e = ensure(h["目标"])
        if e["内力"]:
            e["内力"] = (e["内力"][0], h["新值"])
        else:
            e["内力"] = (h["原值"], h["新值"])

    # 时序变化统一呈现：事件列表 [{目标, 变化(有符号)}, ...]，按目标名折算到各自时序增量。
    # 来源：被攻击反制（on_target_confirmed，如高远无极/反击）、技能特效（on_target_resolved，如百缠手十境）。
    if cmd == "武学":
        def _apply_atb(name, delta):
            if not name:
                return
            e = ensure(name)
            e["时序"] = (e["时序"] or 0) + delta

        for ev in r.get("时序变化", []):
            _apply_atb(ev.get("目标"), ev.get("变化", 0))
        for tr in r.get("目标结算", []):
            for ev in tr.get("时序变化", []):
                _apply_atb(ev.get("目标"), ev.get("变化", 0))

    lines = []
    for name, c in chg.items():
        parts = []
        if c["气血"]:
            parts.append(f"气血 {c['气血'][0]}→{c['气血'][1]}")
        if c["内力"]:
            parts.append(f"内力 {c['内力'][0]}→{c['内力'][1]}")
        for nm, dur in c["gain"]:
            parts.append(f"获得【{nm}】状态" if dur < 0 else f"获得{dur}回合【{nm}】状态")
        for nm in c["lose"]:
            parts.append(f"失去【{nm}】状态")
        for nm, o, n in c["减衰"]:
            parts.append(f"【{nm}】{o}→{n}")
        for nm, o, n in c["延长"]:
            parts.append(f"【{nm}】{o}→{n}")
        if c["时序"]:
            parts.append(f"时序{'+' if c['时序'] > 0 else '-'}{abs(c['时序'])}")
        if parts:
            lines.append(f"`{name} " + "，".join(parts) + "`")

    # 逃跑/认输结局标识行（第三层）
    if cmd == "逃跑":
        lines.append(f"`{actor}逃跑{'成功' if r.get('逃跑成功') else '失败'}`")
    elif cmd == "认输":
        lines.append(f"`{actor}低头认输了`")

    layer3 = "\n".join(lines)
    return layer1 + ("\n" + layer3 if layer3 else "")


def struct_turn_entry(idx, r, is_player=True, skills_db=None):
    """把一条 回合结算（render_turn 第三层箭头行的取值来源）转为结构化明细。

    与文本战报逐字段同源：命中/闪避/伤害/状态/时序等取值路径与 render_turn 一致，
    供战斗 go 返回 回合详情——GM 判读之外，引擎内部打包、web 卡片动画都靠它精确取数。
    skills_db 提供时附 `招式`：与 render_turn 同一轮转序（(回合-1)%len）取招，两边显示一致。
    """
    cmd = r.get("指令") or ""
    actor = r.get("行动者") or ""
    e = {
        "回合": idx,
        "行动者": actor,
        "类型": cmd,
        "操控": "玩家" if is_player else "AI",
    }
    if cmd == "武学":
        e["技能"] = r.get("技能")
        e["目标"] = r.get("目标")
        e["闪避"] = bool(r.get("闪避"))
        if skills_db:
            moves = moves_of(skills_db.get(e["技能"] or "", {}))
            if moves:
                e["招式"] = moves[(idx - 1) % len(moves)]
        for k in ("闪避率", "闪避掷骰"):
            if r.get(k) is not None:
                e[k] = r[k]
        if not e["闪避"]:
            e["暴击"] = bool(r.get("暴击"))
            for k in ("暴击率", "暴击掷骰", "暴击倍率"):
                if r.get(k) is not None:
                    e[k] = r[k]
            e["伤害"] = r.get("伤害", 0)
            if r.get("内力伤害"):
                e["内力伤害"] = r["内力伤害"]
            if r.get("击败"):
                e["击败"] = True
        if r.get("行动者内力变化"):
            e["行动者内力变化"] = r["行动者内力变化"]
        if r.get("行动者气血变化"):
            e["行动者气血变化"] = r["行动者气血变化"]
        if r.get("目标气血变化"):
            e["目标气血变化"] = r["目标气血变化"]
        if r.get("目标内力变化"):
            e["目标内力变化"] = r["目标内力变化"]
        for k in ("施加状态", "状态失效", "时序变化", "加剧负面", "追击结算", "反伤结算", "冷却变化", "状态转移", "移除负面", "移除增益", "霸体抵挡", "强命保命"):
            if r.get(k):
                e[k] = r[k]
        if r.get("目标结算"):
            sub = []
            for tr in r["目标结算"]:
                te = {"目标": tr["目标"], "闪避": bool(tr.get("闪避"))}
                if not te["闪避"]:
                    te["暴击"] = bool(tr.get("暴击"))
                    te["伤害"] = tr.get("伤害", 0)
                    if tr.get("击败"):
                        te["击败"] = True
                for k in ("目标气血变化", "目标内力变化", "施加状态", "时序变化", "加剧负面", "追击结算", "反伤结算", "冷却变化", "状态转移", "移除增益", "霸体抵挡", "强命保命"):
                    if tr.get(k):
                        te[k] = tr[k]
                sub.append(te)
            e["目标结算"] = sub
    elif cmd == "物品":
        e["物品"] = r.get("物品")
        e["物品子类型"] = r.get("物品子类型")
        e["目标"] = r.get("目标")
        for k in ("恢复气血", "恢复内力", "目标气血变化", "目标内力变化",
                  "施加状态", "净化状态", "削减状态", "延长状态", "时序变化",
                  "气血变化", "内力变化"):
            if r.get(k):
                e[k] = r[k]
    elif cmd == "休息":
        e["恢复气血"] = r.get("恢复气血", 0)
        e["恢复内力"] = r.get("恢复内力", 0)
        for k in ("气血变化", "内力变化"):
            if r.get(k):
                e[k] = r[k]
    elif cmd == "逃跑":
        e["逃跑成功"] = bool(r.get("逃跑成功"))
    elif cmd == "认输":
        e["认输"] = True
    elif cmd == "无法行动":
        e["目标"] = actor
        e["原因"] = r.get("原因")
    for k in ("持续伤害", "持续恢复", "持续恢复内力", "状态失效", "时序变化", "特效发动"):
        if r.get(k):
            e[k] = r[k]
    if r.get("状态快照"):
        e["状态快照"] = r["状态快照"]
    return e


def render_results_struct(results, skills_db, start_idx=1, players=None):
    """与 render_results 同源的结构化战报：一条 结算列表 → 一组结构化条目。

    供 engine 战斗 go 附 回合详情；文本战报（render_results 输出）的取值路径不变。"""
    out = []
    players = players or set()
    for i, r in enumerate(results):
        out.append(struct_turn_entry(start_idx + i, r, is_player=(r.get("行动者") in players),
                                     skills_db=skills_db))
    return out


def render_results(results, skills_db, start_idx=1, with_header=False, teams=None):
    """渲染一段结算列表为三层战报文本（纯 AI 整场 / 玩家操控 AI 批次通用）。"""
    lines = []
    if with_header and teams:
        lines.append("、".join("/".join(v) for v in teams.values()) + " 对阵，剑出鞘。")
        lines.append("")
    for i, r in enumerate(results, start_idx):
        lines.append(render_turn(i, r, skills_db))
        lines.append("")
    return "\n".join(lines).rstrip()


def run_battle(chars, seed=None, allow_escape=False):
    """纯 AI：构建状态 → 跑到战斗结束，返回 (结算列表, 胜利阵营, 末状态, 经验结算, 结束方式, 结束方)。"""
    if seed is not None:
        random.seed(seed)
    state = {"角色列表": chars, "回合数": 0, "当前行动者": None, "允许逃跑": allow_escape}
    results = []
    MAX_TURNS = 300  # 平局上限：仅纯AI对战，避免伤害与回血相抵等无法分胜负时死循环
    # （玩家操控交互战不设上限，由玩家自行决定打多久/休息/逃跑脱身）
    while True:
        out = be.auto_advance(state, None, "")
        results.extend(out["结算列表"])
        state = out["战场状态"]
        if out["战斗结束"]:
            return (results, out["战斗结束"], state, out.get("经验结算", {}),
                    out.get("结束方式"), out.get("结束方"))
        if not out["结算列表"]:
            return results, None, state, {}, None, None
        if state.get("回合数", 0) >= MAX_TURNS:
            return results, None, state, {}, None, None  # 超时判平局（战斗未分胜负）


# ========== 持久化（交互战） ==========
def _battle_file(filename, slot):
    """兼容旧调用名：返回按 slot 隔离的新 runtime 文件路径。"""
    return br.file_path(os.path.basename(filename), slot)


def load_state(slot=None):
    state = read_json(br.read_path(STATE_FILE, slot), expected_type=dict)
    # 旧存档续战兼容：缺 物品可用次数 的角色，按当前物品栏补算（上限2）
    for c in state.get("角色列表", []):
        if "物品可用次数" not in c:
            inv0 = c.get("物品", [])
            c["物品可用次数"] = {nm: min(inv0.count(nm), 2) for nm in set(inv0)} if isinstance(inv0, list) else {}
    return state


def save_state(state, slot=None):
    atomic_write_json(br.state_path(slot), state)


def load_meta(slot=None):
    path = br.read_path(META_FILE, slot)
    try:
        meta = read_json(path, expected_type=dict)
    except JsonMissingError:
        return {"n": 0, "players": [DEFAULT_PLAYER], "allow_escape": False}
    # 兼容旧版单 player 字段 → 统一为 players 列表
    if "players" not in meta:
        p = meta.get("player")
        meta["players"] = [p] if isinstance(p, str) else (p or [])
    # 兼容旧版无 allow_escape 字段 → 默认不允许
    meta.setdefault("allow_escape", False)
    return meta


def save_meta(n, players, slot=None, allow_escape=False):
    players = list(players)
    atomic_write_json(
        br.meta_path(slot),
        {"n": n, "players": players, "player": players[0] if players else None,
         "slot": slot, "allow_escape": bool(allow_escape)},
    )


def settle_battle(state, slot):
    """战后写回 .data：存活角色**气血保持战后值、内力补满上限**；败阵者不在此处理（生死由 GM 战后处置：杀/放）。

    仅正式游戏（带 --slot）于战斗结束时调用。只 patch 角色文件中的 气血/内力（及上限同步），
    其余字段（经验/铜钱/物品/关系度/人设/位置等）原样保留。预设 NPC 未落 .data 则跳过。
    """
    cdir = os.path.join(slot_data_dir(slot), "characters")
    data_dir = slot_data_dir(slot)
    report = []
    for c in state.get("角色列表", []):
        name = c["名称"]
        if c.get("气血", 0) <= 0:
            continue  # 败阵：交由 GM 战后处置（杀/放）
        d = dq.read_character_file(name, data_dir=data_dir)
        if d is None:
            continue
        cap_hp = c.get("气血上限", d.get("气血上限"))
        cap_mp = c.get("内力上限", d.get("内力上限"))
        if cap_hp is not None:
            d["气血上限"] = cap_hp
        if cap_mp is not None:
            d["内力上限"] = cap_mp
        d["气血"] = max(0, min(cap_hp, c.get("气血", 0))) if cap_hp else c.get("气血", 0)
        d["内力"] = cap_mp if cap_mp is not None else c.get("内力", 0)  # 战后内力补满
        # 同步战斗中物品栏的消耗（丹药/道具实际扣减处）：以战斗状态副本为准回写
        if "物品" in c:
            d["物品"] = list(c["物品"])
        dq.update_char(name, d, data_dir=data_dir)
        report.append(f"{name}（气血{d['气血']}/{d['气血上限']} 内力{d['内力']}/{d['内力上限']}）")
    return report


def init_state(names, faction_map=None, allow_escape=False):
    return {"角色列表": build_chars(names, faction_map), "回合数": 0,
            "当前行动者": None, "允许逃跑": allow_escape}


# ========== 玩家回合展示 ==========
def buff_name(status_id):
    return be.buff_name_of(status_id)


def buff_label(e):
    """状态标签：长效（剩余时间<0）只作【状态名】、不带时长；限时状态作【状态名】(N)。"""
    d = e.get("剩余时间", 0)
    name = f"【{buff_name(e['id'])}】"
    return name if d < 0 else f"{name}({d})"


def emit_roster_ref(chars, slot=None):
    """战斗人员人设参考：写入 slot runtime 的 battle_report.json，供 GM 写对白参考。

    每次战斗输出（纯 AI 整场 / 交互战开局）覆写该 json，不计入 stdout 战报、不展示给玩家。
    """
    roster = []
    for c in chars:
        name = c["名称"]
        _, persona = dq.get_field("角色", name, "人设")
        persona = persona.strip() if isinstance(persona, str) and persona else ""
        roster.append({"名称": name, "人设": (" " * 500 + persona) if persona else "（无）"})
    atomic_write_json(br.report_path(slot), {"人设参考": roster}, indent=2)


def xinfa_opening_struct(chars, skills_db):
    """开局运功的结构化条目（与 render_xinfa_opening 同源）：各人运转心法得状态，
    用于 battle 返回的 回合详情（web 卡片/动画精确取数）。"""
    out = []
    for c in chars:
        name = c.get("运转心法")
        if not name:
            continue
        skill = skills_db.get(name)
        if not skill or skill.get("类型") != "心法":
            continue
        level = be.get_skill_level(c, name)
        states = []
        for eff in skill.get("心法效果", []):
            gate = eff.get("解锁等级")
            if gate and level < gate:
                continue
            sid = eff.get("施加状态")
            if sid:
                states.append(be.buff_name_of(sid))
        if states:
            out.append({"回合": 0, "类型": "运功", "行动者": c["名称"], "获得状态": states})
    return out


def render_xinfa_opening(chars, skills_db):
    """开局运功三层骨架：第一层各人运功(供 GM 重写) + 第三层状态获取箭头。

    与战局中每回合的三层结构一致，仅描写运功而非攻防。第一层润色优先用内功名，
    第三层状态获取原样用状态名；长效状态不带时长标识。无运转心法者跳过。
    """
    segs = []
    arrow_lines = []
    for c in chars:
        name = c.get("运转心法")
        if not name:
            continue
        skill = skills_db.get(name)
        if not skill or skill.get("类型") != "心法":
            continue
        segs.append(f"{c['名称']}运转【{name}】")
        states = []
        level = be.get_skill_level(c, name)
        for eff in skill.get("心法效果", []):
            gate = eff.get("解锁等级")
            if gate and level < gate:
                continue  # 未达境界门控，实际未施加，不渲染
            sid = eff.get("施加状态")
            if not sid:
                continue
            # 第三层原样用状态名（与每回合第三层一致）；第一层润色方优先用内功名
            states.append(be.buff_name_of(sid))
        if states:
            joined = "、".join(f"【{s}】" for s in states)
            arrow_lines.append(f"`{c['名称']} 获得{joined}状态`")
    if not segs:
        return ""
    layer1 = "、".join(segs) + "。"
    layer3 = "\n".join(arrow_lines)
    return layer1 + ("\n" + layer3 if layer3 else "")


def available_skills(char, skills_db, characters_db, chars):
    # 可用武学取 携带技能（配置上场，至多4门）；缺省回退全部已习得（心法/武器/冷却/内力在下方过滤）
    names = be.get_active_skill_names(char, characters_db)
    cd = char.get("冷却", {})
    type_to_weapon = {"剑法": "剑", "刀法": "刀", "长兵": "长兵", "奇门": "奇门", "暗器": "暗器"}
    equip = char.get("装备", {})
    items_db = be.load_items()
    weapon_types = []
    for slot in ["武器1", "武器2"]:
        w = equip.get(slot)
        if w:
            info = items_db.get(w) if isinstance(w, str) else None
            if info:
                weapon_types.append(info.get("子类型"))
    out = []
    for name in names:
        base = skills_db.get(name)
        if not base:
            continue
        # 心法不可主动使用，不列入可用武学
        if base.get("类型") == "心法":
            continue
        level = be.get_skill_level(char, name, characters_db)
        rskill = be.resolve_skill(base, level)
        skill_type = rskill.get("类型")
        weapon_ok = True
        if skill_type and skill_type != "搏击":
            req = type_to_weapon.get(skill_type)
            if req and req not in weapon_types:
                weapon_ok = False
        # 消耗可支付性（结算事件 dry-run；【七星逆脉】改耗气血时按气血判定，键名沿用）
        blocked = be.cost_blocked_reason(char, rskill["内力消耗"], chars, name)
        # 状态技能过滤（如【封穴】禁用一切武学、【封技】禁特定品级）：被禁则不可用
        sealed = not be.skill_available(char, base)
        out.append({
            "名称": name, "等级": level, "类型": skill_type or "—",
            "威力倍率": round(rskill["威力倍率"], 2),
            "内力消耗": rskill["内力消耗"],
            "冷却时间": be.display_cooldown(char, rskill),
            "冷却中": name in cd, "冷却剩余": cd.get(name, 0),
            "内力不足": blocked is not None,
            "不足原因": blocked,
            "武器不符": not weapon_ok,
            "封禁": sealed,
        })
    return out


def fmt_status(char):
    name = char["名称"]
    if char.get("逃走"):
        return f"{name}（逃走）"
    if char.get("气血", 0) <= 0:
        return f"{name}（败阵）"
    hp = f"气血({char['气血']}/{be.status_attr(char, '气血上限')})"
    mp_cap = be.status_attr(char, "内力上限")
    mp = f"内力({char['内力']}/{mp_cap})"
    effs = char.get("状态效果", [])
    st = "、".join(buff_label(e) for e in effs) if effs else "无"
    cds = char.get("冷却", {})
    cd_str = (" 冷却[" + "、".join(f"{k}:{v}" for k, v in cds.items()) + "]") if cds else ""
    return f"{name} {hp} {mp} 状态（{st}）{cd_str}".rstrip()


def render_status_table(chars, side=None):
    """渲染战斗状态表为字符串。side 为当前操控角色所在阵营，命中标「我方」，余标「敌方」；None 时省略该列。"""
    cols = (["阵营"] if side is not None else []) + ["名称", "气血", "内力", "状态", "冷却"]
    rows = []
    for c in chars:
        name = c["名称"]
        is_mine = side is not None and c["阵营"] == side
        side_label = ("我方" if is_mine else "敌方") if side is not None else None
        disp_name = f"`{name}`" if is_mine else name  # 我方名称反引号高亮
        if c.get("逃走"):
            row = ([side_label] if side is not None else []) + [disp_name, "逃走", "", "", ""]
            rows.append(row)
            continue
        if c.get("气血", 0) <= 0:
            row = ([side_label] if side is not None else []) + [disp_name, "败阵", "", "", ""]
            rows.append(row)
            continue
        hp = f"{c['气血']}/{be.status_attr(c, '气血上限')}"
        mp = f"{c['内力']}/{be.status_attr(c, '内力上限')}"
        effs = c.get("状态效果", [])
        st = "、".join(buff_label(e) for e in effs) if effs else "无"
        cds = c.get("冷却", {})
        cd_str = "、".join(f"{k}:{v}" for k, v in cds.items()) if cds else "无"
        row = ([side_label] if side is not None else []) + [disp_name, hp, mp, st, cd_str]
        rows.append(row)
    widths = [max(len(str(r[i])) for r in ([cols] + [x for x in rows if x])) for i in range(len(cols))]
    lines = []
    lines.append("| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cols)) + " |")
    lines.append("| " + " | ".join("-" * widths[i] for i in range(len(cols))) + " |")
    for r in rows:
        lines.append("| " + " | ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)) + " |")
    return "\n".join(lines)


def render_player_prompt(state, skills_db, characters_db):
    """渲染玩家回合界面为字符串（状态表 + 行动预告 + 可用武学/物品 + 指令提示）。"""
    chars = state["角色列表"]
    me = next(c for c in chars if c["名称"] == PLAYER)
    enemies = [c for c in chars if c["阵营"] != me["阵营"] and be.is_in_fight(c)]
    L = []
    L.append("")
    L.append(f"轮到你了！行动角色：{PLAYER}")
    L.append("")
    L.append(render_status_table(chars, side=me["阵营"]))
    L.append("")
    order = be.predict_action_order(chars)
    L.append(f"行动预告：【{PLAYER}】→ " + " → ".join(order[:5]))
    L.append("")
    L.append("可用武学：")
    for s in available_skills(me, skills_db, characters_db, chars):
        flags = []
        if s["冷却中"]:
            flags.append(f"冷却中(剩{int(s['冷却剩余'])}回合)")
        if s["内力不足"]:
            flags.append(s.get("不足原因") or "内力不足")
        if s["武器不符"]:
            flags.append("武器不符")
        if not flags:
            flags.append("可用")
        flag_str = " —— " + "，".join(flags)
        cd_info = f" / 冷却{s['冷却时间']}" if s["冷却时间"] else " / 无冷却"
        scope = skills_db.get(s["名称"], {}).get("目标范围")
        scope_info = " / " + (scope or "敌方单体")
        L.append(f"- `{s['名称']}`（{s['类型']}{scope_info} / 威力{s['威力倍率']} / 内力{s['内力消耗']}{cd_info}）{flag_str}")
        desc = dq.effect_desc_of(skills_db.get(s["名称"], {}), s["等级"])
        L.append(f"　特效：{desc}")
    L.append("")
    me = next(c for c in state["角色列表"] if c["名称"] == PLAYER)
    items_db = be.load_items()
    def _eff_str(n):
        eff = items_db.get(n, {}).get("使用效果", {})
        parts = []
        if "回复气血" in eff:
            parts.append(f"回复气血{eff['回复气血']}")
        if "回复内力" in eff:
            parts.append(f"回复内力{eff['回复内力']}")
        st = eff.get("施加状态")
        if st:
            parts.append(f"施加状态{st.get('回合', 1)}回合")
        if "时序" in eff:
            parts.append(f"时序{eff['时序']:+d}")
        if "净化" in eff:
            parts.append(f"随机净化{eff['净化']}个非长效负面状态")
        if "削减" in eff:
            parts.append(f"所有非长效负面状态剩余-{eff['削减']}回合")
        if "延长" in eff:
            parts.append(f"所有非长效正面状态剩余+{eff['延长']}回合")
        return "、".join(parts) or "—"
    battle_items = be.get_battle_items(me, items_db)
    inv = me.get("物品", [])
    avail = me.get("物品可用次数", {})
    if battle_items:
        L.append("可用物品：")
        for n in battle_items:
            if avail.get(n, 0) <= 0:
                continue
            sub = items_db.get(n, {}).get("子类型")
            direction = "对敌方" if sub == "道具" else "对我方"
            count = avail.get(n, 0)
            L.append(f"- `{n}` × {count}")
            L.append(f"　效果：{_eff_str(n)}（{direction}）")
        L.append("")
    L.append("请输入指令（使用武学、使用物品、查看人物信息、休息、逃跑、认输）：")
    return "\n".join(L)


def build_player_action(state, skills_db, characters_db):
    """构建玩家回合的结构化「行动信息」（与 render_player_prompt 同源），供 WEB_UI 前端解析渲染。
    返回 {行动者, 行动顺序, 状态表, 可用武学, 可用物品}：
      · 行动者：当前受控角色名
      · 行动顺序：be.predict_action_order 结果（当前行动者之后的序，前端据此拼行动链）
      · 状态表：全体在战人员 [{阵营,名称,气血:{当前,上限},内力:{当前,上限},状态:[],冷却:[],败阵,逃走}]
      · 可用武学：携带武学 [{名称,类型,范围,威力,内力,冷却,冷却中,冷却剩余,内力不足,武器不符,可用,特效}]（≤4）
      · 可用物品：战斗携带消耗品 [{名称,数量,效果,方向}]（≤4）
    """
    chars = state["角色列表"]
    me = next(c for c in chars if c["名称"] == PLAYER)

    # 状态表
    状态表 = []
    for c in chars:
        name = c["名称"]
        side_label = "我方" if c["阵营"] == me["阵营"] else "敌方"
        if c.get("逃走"):
            状态表.append({"阵营": side_label, "名称": name,
                            "气血": {"当前": 0, "上限": be.status_attr(c, "气血上限")},
                            "内力": {"当前": 0, "上限": be.status_attr(c, "内力上限")},
                            "状态": [], "冷却": [], "败阵": False, "逃走": True})
            continue
        if c.get("气血", 0) <= 0:
            状态表.append({"阵营": side_label, "名称": name,
                            "气血": {"当前": 0, "上限": be.status_attr(c, "气血上限")},
                            "内力": {"当前": 0, "上限": be.status_attr(c, "内力上限")},
                            "状态": [], "冷却": [], "败阵": True, "逃走": False})
            continue
        effs = c.get("状态效果", [])
        st = [buff_label(e) for e in effs]
        cds = c.get("冷却", {})
        cd_list = [f"{k}:{v}" for k, v in cds.items()]
        状态表.append({"阵营": side_label, "名称": name,
                        "气血": {"当前": c["气血"], "上限": be.status_attr(c, "气血上限")},
                        "内力": {"当前": c["内力"], "上限": be.status_attr(c, "内力上限")},
                        "状态": st, "冷却": cd_list, "败阵": False, "逃走": False})

    # 可用武学
    可用武学 = []
    for s in available_skills(me, skills_db, characters_db, chars):
        scope = skills_db.get(s["名称"], {}).get("目标范围") or "敌方单体"
        cd_info = s["冷却时间"] or "无冷却"
        可用武学.append({
            "名称": s["名称"], "类型": s["类型"], "范围": scope,
            "威力": s["威力倍率"], "内力": s["内力消耗"], "冷却": cd_info,
            "冷却中": bool(s["冷却中"]), "冷却剩余": int(s["冷却剩余"]),
            "内力不足": bool(s["内力不足"]), "武器不符": bool(s["武器不符"]),
            "封禁": bool(s["封禁"]),
            "可用": not (s["冷却中"] or s["内力不足"] or s["武器不符"] or s["封禁"]),
            "特效": dq.effect_desc_of(skills_db.get(s["名称"], {}), s["等级"]),
        })

    # 可用物品
    可用物品 = []
    items_db = be.load_items()
    battle_items = be.get_battle_items(me, items_db)
    inv = me.get("物品", [])
    avail = me.get("物品可用次数", {})
    for n in battle_items:
        if avail.get(n, 0) <= 0:
            continue
        rec = items_db.get(n, {})
        # 状态物品过滤（如【封穴】禁用一切物品）：被禁则不可用
        item_sealed = not be.item_available(me, rec)
        sub = rec.get("子类型")
        direction = "对敌方" if sub == "道具" else "对我方"
        eff = rec.get("使用效果", {})
        parts = []
        if "回复气血" in eff:
            parts.append(f"回复气血{eff['回复气血']}")
        if "回复内力" in eff:
            parts.append(f"回复内力{eff['回复内力']}")
        st = eff.get("施加状态")
        if st:
            parts.append(f"施加状态{st.get('回合', 1)}回合")
        if "时序" in eff:
            parts.append(f"时序{eff['时序']:+d}")
        if "净化" in eff:
            parts.append(f"随机净化{eff['净化']}个非长效负面状态")
        if "削减" in eff:
            parts.append(f"所有非长效负面状态剩余-{eff['削减']}回合")
        if "延长" in eff:
            parts.append(f"所有非长效正面状态剩余+{eff['延长']}回合")
        可用物品.append({"名称": n, "数量": avail.get(n, 0),
                         "效果": "、".join(parts) or "—", "方向": direction,
                         "封禁": item_sealed, "可用": not item_sealed})

    return {
        "行动者": PLAYER,
        "行动顺序": be.predict_action_order(chars),
        "状态表": 状态表,
        "可用武学": 可用武学,
        "可用物品": 可用物品,
    }


def render_char_info(state):
    cols = ["名称", "阵营", "气血", "内力", "攻击力", "防御力",
            "速度", "精准", "识破", "暴击", "剑法", "搏击", "暗器"]
    rows = []
    for c in state["角色列表"]:
        if c.get("逃走"):
            rows.append([c["名称"], c["阵营"], "逃走"])
        elif c.get("气血", 0) <= 0:
            rows.append([c["名称"], c["阵营"], "败阵"])
            continue
        sec = c.get("二级属性", {})
        wy = c.get("武艺", {})
        rows.append([c["名称"], c["阵营"], f"{c['气血']}/{be.status_attr(c, '气血上限')}", f"{c['内力']}/{be.status_attr(c, '内力上限')}",
                     sec.get("攻击力"), sec.get("防御力"), sec.get("速度"), sec.get("精准"),
                     sec.get("识破"), sec.get("暴击"), wy.get("剑法"), wy.get("搏击"), wy.get("暗器")])
    rows = [[str(x) for x in r] for r in rows]
    widths = [max(len(r[i]) for r in [cols] + rows) for i in range(len(cols))]
    lines = []
    lines.append("| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)) + " |")
    lines.append("| " + " | ".join("-" * widths[i] for i in range(len(cols))) + " |")
    for r in rows:
        lines.append("| " + " | ".join(v.ljust(widths[i]) for i, v in enumerate(r)) + " |")
    return "\n".join(lines)


SEC_ORDER = ["气血上限", "内力上限", "攻击力", "防御力", "速度", "精准", "识破", "暴击", "经验加成"]


def show_stats(names):
    """输出一个或多个角色派生后的完整属性（基础派生 + 武学反哺 + 装备加成，与战斗同源）。"""
    for name in names:
        try:
            c = derive_char(name)
        except FileNotFoundError:
            print(f"未找到角色【{name}】（经 dao 扫描各门派子目录未找到）")
            continue
        sec, wy = c["二级属性"], c["武艺"]
        prim, pol = c["一级属性"], c["极性"]
        print(f"【{name}】派生属性（基础派生 + 武学反哺 + 装备加成，与战斗同源）")
        print(f"  一级属性  内功{prim['内功']} 力道{prim['力道']} 身法{prim['身法']} 根骨{prim['根骨']}"
              f"   极性 内功{pol['内功']}/力道{pol['力道']}/身法{pol['身法']}/根骨{pol['根骨']}")
        wuxue = "、".join(
            f"{e['名称']}({e.get('等级', 1)})" if isinstance(e, dict) else f"{e}(1)"
            for e in c.get("武学", []))
        print(f"  武学      {wuxue or '—'}")
        equip = c.get("装备", {})
        eq_parts = [f"{k}:{v}" for k, v in equip.items() if v]
        print(f"  装备      {'、'.join(eq_parts) or '无'}")
        sec_str = "  ".join(f"{k}{sec[k]}{'%' if k == '经验加成' else ''}" for k in SEC_ORDER)
        print(f"  二级属性  {sec_str}")
        print(f"  武艺      剑法{wy.get('剑法', 0)} 搏击{wy.get('搏击', 0)} 刀法{wy.get('刀法', 0)}"
              f" 长兵{wy.get('长兵', 0)} 奇门{wy.get('奇门', 0)} 暗器{wy.get('暗器', 0)}")
        jy = c.get("技艺", {})
        if jy:
            print(f"  技艺      音律{jy.get('音律', 0)} 弈棋{jy.get('弈棋', 0)} 诗书{jy.get('诗书', 0)}"
                  f" 绘画{jy.get('绘画', 0)} 医术{jy.get('医术', 0)} 博物{jy.get('博物', 0)}")
        print()


# ========== 指令解析 ==========
def parse_player_input(text, state, skills_db, characters_db):
    """把玩家自然语言/JSON 指令解析为引擎 action。返回 (action, 错误消息)。"""
    text = text.strip()
    if not text:
        return None, "指令为空"
    if text.startswith("{"):
        try:
            return json.loads(text), None
        except Exception as e:
            return None, f"JSON 解析失败：{e}"
    if text.startswith("休息"):
        return {"类型": "休息"}, None
    if "查看" in text or "人物信息" in text:
        return {"类型": "查看信息"}, None
    if text.startswith("武学"):
        parts = [p for p in text[2:].split() if p]
        if not parts:
            return None, "请指明技能名，例：武学 天道三垣剑 朱如碧"
        skill_name = parts[0]
        me = next(c for c in state["角色列表"] if c["名称"] == PLAYER)
        active = be.get_active_skill_names(me, characters_db)
        if skill_name not in active:
            return None, f"【{skill_name}】未配置上场，当前携带：{'、'.join(active) or '无'}"
        skill = skills_db.get(skill_name)
        if skill and skill.get("类型") == "心法":
            return None, f"【{skill_name}】为心法，无法主动使用（仅可运转）"
        # 状态技能过滤（如【封穴】禁用一切武学、【封技】禁特定品级）：被禁则拒出
        if skill and not be.skill_available(me, skill):
            return None, f"武学被封禁，无法使用【{skill_name}】"
        # 敌方全体武学：无需指定单体目标，剑气横扫敌方全体
        if skill and skill.get("目标范围") == "敌方全体":
            foes = [c["名称"] for c in state["角色列表"]
                    if c["阵营"] != me["阵营"] and be.is_in_fight(c)]
            if not foes:
                return None, "场上无可攻击的敌方目标"
            return {"类型": "武学", "技能": skill, "目标": "敌方全体"}, None
        if len(parts) < 2:
            return None, "请指明目标，例：武学 天道三垣剑 朱如碧"
        target = parts[1]
        target_char = next((c for c in state["角色列表"] if c["名称"] == target), None)
        if not target_char or not be.is_in_fight(target_char):
            foes = [c["名称"] for c in state["角色列表"]
                    if c["阵营"] != me["阵营"] and be.is_in_fight(c)]
            return None, f"目标【{target}】不存在或已败阵，可选：{'、'.join(foes) or '无'}"
        if target_char["阵营"] == me["阵营"]:
            return None, "不能攻击同阵营目标"
        return {"类型": "武学", "技能": skill, "目标": target}, None
    if text.startswith("使用"):
        items_db = be.load_items()
        parts = [p for p in text[2:].split() if p]
        if not parts:
            return None, "请指明物品名，例：使用 小还丹（丹药，默认自己）/ 使用 石灰粉 骆逸（道具，默认首个敌方）"
        item_name = parts[0]
        me = next(c for c in state["角色列表"] if c["名称"] == PLAYER)
        inv = me.get("物品", [])
        battle_items = be.get_battle_items(me, items_db)
        if item_name not in battle_items:
            return None, f"【{item_name}】未配置上场（战斗最多携带4类消耗品），当前上场：{'、'.join(battle_items) or '无'}"
        if item_name not in inv:
            return None, f"物品栏无【{item_name}】（已耗尽），现有：{'、'.join(inv) or '无'}"
        item = items_db.get(item_name)
        if not item or item.get("类型") != "消耗品":
            return None, f"【{item_name}】非消耗品，无法使用"
        # 状态物品过滤（如【封穴】禁用一切物品）：被禁则拒出
        if not be.item_available(me, item):
            return None, f"被封穴，无法使用物品【{item_name}】"
        foes = [c["名称"] for c in state["角色列表"]
                if c["阵营"] != me["阵营"] and be.is_in_fight(c)]
        allies = [c["名称"] for c in state["角色列表"]
                  if c["阵营"] == me["阵营"] and be.is_in_fight(c)]
        if item.get("子类型") == "道具":
            target = parts[1] if len(parts) >= 2 else (foes[0] if foes else None)
            if not target:
                return None, "场上无敌方目标，道具无法使用"
            if target not in foes:
                return None, f"道具只能对敌方使用，可选敌方：{'、'.join(foes) or '无'}"
        else:  # 丹药等对我方使用的消耗品
            target = parts[1] if len(parts) >= 2 else PLAYER
            if target not in allies:
                return None, f"丹药只能对我方使用，可选我方：{'、'.join(allies) or '无'}"
        return {"类型": "物品", "物品": item, "目标": target}, None
    return None, "无法识别指令。可用：使用武学 / 使用物品 / 查看人物 / 休息 / 逃跑 / 认输"


# ========== 统一 JSON 输出 ==========

def _side_of(state, player_name):
    """据玩家操控角色名取其阵营（我方）；player_name 为空时取首角色阵营。"""
    chars = state["角色列表"]
    if player_name:
        me = next((c for c in chars if c["名称"] == player_name), None)
        if me:
            return me["阵营"]
    return chars[0]["阵营"] if chars else None


def battle_status_of(winner, my_side, end_mode=None, end_side=None, draw=False):
    """战局状态 → 我方视角字符串。winner 为胜方阵营（None=未结束/平局/"逃跑"）。
    end_mode="逃跑"/"认输" 时据 end_side（结束方阵营）判我方/敌方；draw=平局。"""
    if end_mode == "逃跑":
        return "我方逃跑" if end_side == my_side else "敌方逃跑"
    if end_mode == "认输":
        return "我方认输" if end_side == my_side else "敌方认输"
    if draw:
        return "平局"
    if not winner or winner == "逃跑":
        return "进行中"
    return "我方胜" if winner == my_side else "我方败"


def emit_battle_json(state, report, player_ui=None, winner=None,
                     my_side=None, end_mode=None, end_side=None, draw=False, turns=None,
                     回合详情=None, 行动预告=None, 行动信息=None):
    """统一输出战斗 JSON：{战局状态, 战报, 玩家界面/行动信息}。
    - 战局状态：状态(我方视角)/回合数/我方/敌方/战果(战斗结束时：{角色名:存活|逃走|败阵})
    - 战报：本轮三层战报+结算行渲染文本（无内容则空串）——LLM 模式
    - 玩家界面：玩家回合界面文本（仅进行中、轮到玩家时；否则 None）——LLM 模式
    - 行动信息：玩家回合结构化数据（同上条件）——WEB_UI 模式，前端解析渲染
    战斗结束（winner 非空或 end_mode 非空）时附 `战果`：双方人员名称→最终状态。
    """
    chars = state.get("角色列表", [])
    teams = {}
    for c in chars:
        teams.setdefault(c["阵营"], []).append(c["名称"])
    side_list = list(teams.keys())
    if my_side is None:
        my_side = side_list[0] if side_list else None
    my_team = teams.get(my_side, [])
    enemy_team = [n for s, ns in teams.items() if s != my_side for n in ns]
    status = battle_status_of(winner, my_side, end_mode=end_mode, end_side=end_side, draw=draw)
    ended = bool(winner) or bool(end_mode) or draw
    battle_state = {
        "状态": status,
        "回合数": turns if turns is not None else state.get("回合数", 0),
        "我方": _roster_with_status(state, my_team, ended=ended),
        "敌方": _roster_with_status(state, enemy_team, ended=ended),
    }
    # 渲染模式：WUXIA_RPG_RENDER_MODULE=LLM（缺省）→ 文本战报+玩家界面；
    # 否则（WEB_UI）→ 结构化回合详情+行动信息。
    # 战局状态/战果为战况状态、行动预告为行动顺序，两种模式均带。
    llm_mode = os.environ.get("WUXIA_RPG_RENDER_MODULE", "LLM") == "LLM"
    payload = {"战局状态": battle_state}
    if llm_mode:
        payload["战报"] = report or ""
        if player_ui is not None:
            payload["玩家界面"] = player_ui
    else:
        if 回合详情 is not None:
            payload["回合详情"] = 回合详情
        if 行动信息 is not None:
            payload["行动信息"] = 行动信息
    if 行动预告 is not None:
        payload["行动预告"] = 行动预告
    if ended:
        status_map = {s.get("名称"): _char_status(s) for s in state.get("状态摘要", [])}
        payload["战果"] = {
            c["名称"]: ("逃走" if status_map.get(c["名称"]) == "逃走"
                        else ("败阵" if status_map.get(c["名称"]) == "败阵" else "存活"))
            for c in chars
        }
    print(json.dumps(payload, ensure_ascii=False))


def _char_status(s):
    """据状态摘要条目取个人实时状态：逃走/败阵/战斗中（在场且气血>0）。"""
    st = s.get("状态")
    if st == "逃走":
        return "逃走"
    if st == "败阵":
        return "败阵"
    return "战斗中"


def _roster_with_status(state, names, ended=False):
    """把名单渲染为 [角色名：状态] 形式，状态实时取自状态摘要。
    ended=True（战斗已结束）时在场者显示「存活」，否则显示「战斗中」。"""
    status_map = {s.get("名称"): _char_status(s) for s in state.get("状态摘要", [])}
    live = "存活" if ended else "战斗中"
    out = []
    for n in names:
        st = status_map.get(n)
        if st in ("逃走", "败阵"):
            out.append(f"{n}：{st}")
        else:
            out.append(f"{n}：{live}")
    return out


# ========== 主流程 ==========
def resolve_player(names, player_arg):
    if player_arg:
        return player_arg
    return DEFAULT_PLAYER if DEFAULT_PLAYER in names else names[0]


def pure_ai(names, seed, faction_map=None, slot=None, allow_escape=False):
    """纯 AI 对战：构建角色 → 跑到结束 → 渲染整场三层战报，输出 JSON。"""
    chars = build_chars(names, faction_map)
    results, winner, state, exp_gain, end_mode, end_side = run_battle(chars, seed, allow_escape=allow_escape)
    skills_db = be.load_skills()
    teams = {}
    for c in chars:
        teams.setdefault(c["阵营"], []).append(c["名称"])
    body = render_results(results, skills_db, start_idx=1, with_header=True, teams=teams)
    opening = render_xinfa_opening(chars, skills_db)
    if opening:
        # 在对阵概览行与首回合之间插入开局运功三层骨架
        parts = body.split("\n", 2)
        body = parts[0] + "\n\n" + opening + (("\n\n" + parts[2]) if len(parts) > 2 else "")
    draw = not winner
    out = [body]
    if winner == "逃跑":
        out.append(f"**战斗结束 · 逃跑**（共 {len(results)} 回合）")
    elif winner:
        out.append(f"**战斗结束 · {winner}胜**（共 {len(results)} 回合）")
    else:
        out.append(f"**战斗未分胜负**（共 {len(results)} 回合）")
    summary = state.get("状态摘要", [])
    surv = [s for s in summary if s.get("气血", 0) > 0]
    dead = [s["名称"] for s in summary if s.get("状态") == "败阵"]
    fled = [s["名称"] for s in summary if s.get("状态") == "逃走"]
    if surv:
        out.append("存活：" + "、".join(f"{s['名称']}（气血{s['气血']}/{s['气血上限']}）" for s in surv))
    if fled:
        out.append("逃走：" + "、".join(fled))
    if dead:
        out.append("败阵：" + "、".join(dead))
    if slot is not None:
        rep = settle_battle(state, slot)
        if rep:
            out.append("战后写回 .data（内力补满，气血保持）：" + "、".join(rep))
    if exp_gain:
        out.append("经验结算：" + "、".join(f"{n} +{v}" for n, v in exp_gain.items()))
    report = "\n".join(out)
    details = xinfa_opening_struct(chars, skills_db)
    details += render_results_struct(results, skills_db, start_idx=1, players=None)
    emit_battle_json(state, report, winner=winner, draw=draw,
                     end_mode=end_mode, end_side=end_side, turns=len(results), 回合详情=details)
    emit_roster_ref(chars, slot)  # 人设参考写入 slot runtime，供 GM 写对白用，不进 stdout 战报


def run_init(names, players, seed, faction_map=None, slot=None, allow_escape=False):
    """交互战开局：推进到首个受控角色回合并展示提示。players 为受控角色名列表。

    allow_escape：GM 据剧情人设在**战前**判定的本场是否允许逃跑，写入 meta 供逃跑指令读取。
    """
    global PLAYER
    if isinstance(players, str):
        players = [players]
    if seed is not None:
        random.seed(seed)
    skills_db = be.load_skills()
    characters_db = be.load_characters()
    state = init_state(names, faction_map, allow_escape=allow_escape)
    out = be.auto_advance(state, None, None, set(players))
    results = out["结算列表"]
    state = out["战场状态"]
    pred = out.get("行动预告")
    teams = {}
    for c in state["角色列表"]:
        teams.setdefault(c["阵营"], []).append(c["名称"])
    report_lines = ["、".join("/".join(v) for v in teams.values()) + " 对阵，剑出鞘。"]
    opening = render_xinfa_opening(state["角色列表"], skills_db)
    if opening:
        report_lines.append("")
        report_lines.append(opening)
    text = render_results(results, skills_db, start_idx=1)
    if text.strip():
        report_lines.append("")
        report_lines.append(text)
    report = "\n".join(report_lines)
    save_meta(len(results), players, slot, allow_escape=allow_escape)
    save_state(state, slot)
    emit_roster_ref(state["角色列表"], slot)
    my_side = _side_of(state, players[0] if players else None)
    details = xinfa_opening_struct(state["角色列表"], skills_db)
    details += render_results_struct(results, skills_db, start_idx=1, players=set(players))
    if out["战斗结束"]:
        settle_lines = [report, "", f"**战斗结束 · {out['战斗结束']}胜**"]
        if slot is not None:
            rep = settle_battle(state, slot)
            if rep:
                settle_lines.append("战后写回 .data（内力补满，气血保持）：" + "、".join(rep))
        emit_battle_json(state, "\n".join(settle_lines),
                         winner=out["战斗结束"], my_side=my_side,
                         end_mode=out.get("结束方式"), end_side=out.get("结束方"),
                         回合详情=details, 行动预告=pred)
        return
    PLAYER = state["当前行动者"]
    player_ui = render_player_prompt(state, skills_db, characters_db)
    action_info = build_player_action(state, skills_db, characters_db)
    emit_battle_json(state, report, player_ui=player_ui, my_side=my_side,
                     回合详情=details, 行动预告=pred, 行动信息=action_info)


def run_step(instruction, slot=None):
    """交互战推进：执行玩家指令 + 后续 AI 回合，直到再次轮到玩家或结束。slot 定位隔离的临时文件。

    逃跑许可由开局 `run_init` 据剧情人设判定、写入 meta；此处读 meta.allow_escape：
    玩家输入「逃跑」时，若为 False 则拒绝（不推进、不消耗回合，重展玩家回合界面）；
    为 True 则掷骰判定，成功即脱战结束（不发经验，仅战后数据写回），失败亦重展界面继续战斗。
    """
    global PLAYER
    meta = load_meta(slot)
    players = meta["players"]
    allow_escape = meta.get("allow_escape", False)
    skills_db = be.load_skills()
    characters_db = be.load_characters()
    state = load_state(slot)
    PLAYER = state["当前行动者"]  # 当前轮到的受控角色，parse_player_input/show 据此取 me

    # 逃跑指令：读开局判定的逃跑许可，再掷骰判定
    if instruction.strip().startswith("逃跑"):
        my_side = _side_of(state, PLAYER)
        if not allow_escape:
            report = "`无法逃跑——此战不容脱身（GM 战前据剧情人设判定）`"
            player_ui = render_player_prompt(state, skills_db, characters_db)
            action_info = build_player_action(state, skills_db, characters_db)
            emit_battle_json(state, report, player_ui=player_ui, my_side=my_side,
                             行动信息=action_info)
            return
        out = be.attempt_escape(state, PLAYER)
        battle_slot = meta.get("slot")
        if out["逃跑成功"]:
            # 个人结算：逃跑者逃走、战斗继续。推进 AI 回合（敌方趁隙追击）
            st = out["战场状态"]
            esc_text = render_turn(meta["n"] + 1,
                                   {"行动者": PLAYER, "指令": "逃跑", "逃跑成功": True}, skills_db)
            adv = be.auto_advance(st, None, PLAYER, set(players))
            ai_results = adv["结算列表"]
            st = adv["战场状态"]
            pred = adv.get("行动预告")
            save_meta(meta["n"] + 1 + len(ai_results), players, battle_slot, allow_escape=allow_escape)
            save_state(st, battle_slot)
            ai_text = render_results(ai_results, skills_db, start_idx=meta["n"] + 2)
            report = esc_text
            if ai_text.strip():
                report += "\n\n" + ai_text
            flee_detail = [{"回合": meta["n"] + 1, "行动者": PLAYER, "类型": "逃跑",
                            "指令": "逃跑", "逃跑成功": True}]
            flee_detail += render_results_struct(ai_results, skills_db,
                                                 start_idx=meta["n"] + 2, players=set(players))
            if adv["战斗结束"]:
                # 因逃跑致一方全员不在场（或敌方追击致终），按正常胜负结束
                total = st.get("回合数", meta["n"] + 1 + len(ai_results))
                end_lines = [report, "", f"**战斗结束 · {adv['战斗结束']}胜**（共 {total} 回合）"]
                summary = st.get("状态摘要", [])
                surv = [s for s in summary if s.get("气血", 0) > 0]
                dead = [s["名称"] for s in summary if s.get("状态") == "败阵"]
                fled = [s["名称"] for s in summary if s.get("状态") == "逃走"]
                if surv:
                    end_lines.append("存活：" + "、".join(f"{s['名称']}（气血{s['气血']}/{s['气血上限']}）" for s in surv))
                if fled:
                    end_lines.append("逃走：" + "、".join(fled))
                if dead:
                    end_lines.append("败阵：" + "、".join(dead))
                if battle_slot is not None:
                    rep = settle_battle(st, battle_slot)
                    if rep:
                        end_lines.append("战后写回 .data（内力补满，气血保持）：" + "、".join(rep))
                exp_gain = adv.get("经验结算") or {}
                if exp_gain:
                    end_lines.append("经验结算：" + "、".join(f"{n} +{v}" for n, v in exp_gain.items()))
                emit_battle_json(st, "\n".join(end_lines), winner=adv["战斗结束"],
                                 my_side=my_side, turns=total,
                                 end_mode=adv.get("结束方式"), end_side=adv.get("结束方"),
                                 回合详情=flee_detail, 行动预告=pred)
                return
            # 战斗继续：轮到下一个受控角色
            PLAYER = st["当前行动者"]
            player_ui = render_player_prompt(st, skills_db, characters_db)
            action_info = build_player_action(st, skills_db, characters_db)
            emit_battle_json(st, report, player_ui=player_ui, my_side=my_side,
                             回合详情=flee_detail, 行动预告=pred, 行动信息=action_info)
            return
        # 逃跑判定失败：本回合结束（消耗玩家本次行动权，充能-100，与出招同等），推进 AI 回合（敌方趁隙追击）
        st = out["战场状态"]
        me = next(c for c in st["角色列表"] if c["名称"] == PLAYER)
        me["充能"] -= 100
        adv = be.auto_advance(st, None, PLAYER, set(players))
        ai_results = adv["结算列表"]
        st = adv["战场状态"]
        pred = adv.get("行动预告")
        battle_slot = meta.get("slot")
        save_meta(meta["n"] + 1 + len(ai_results), players, battle_slot, allow_escape=allow_escape)
        save_state(st, battle_slot)
        ai_text = render_results(ai_results, skills_db, start_idx=meta["n"] + 2)
        fail_text = render_turn(meta["n"] + 1, {"行动者": PLAYER, "指令": "逃跑", "逃跑成功": False}, skills_db)
        report = fail_text
        if ai_text.strip():
            report += "\n\n" + ai_text
        flee_detail = [{"回合": meta["n"] + 1, "行动者": PLAYER, "类型": "逃跑",
                        "指令": "逃跑", "逃跑成功": False}]
        flee_detail += render_results_struct(ai_results, skills_db,
                                             start_idx=meta["n"] + 2, players=set(players))
        if adv["战斗结束"]:
            total = st.get("回合数", meta["n"] + 1 + len(ai_results))
            end_lines = [report, "", f"**战斗结束 · {adv['战斗结束']}胜**（共 {total} 回合）"]
            summary = st.get("状态摘要", [])
            surv = [s for s in summary if s.get("气血", 0) > 0]
            dead = [s["名称"] for s in summary if s.get("状态") == "败阵"]
            fled = [s["名称"] for s in summary if s.get("状态") == "逃走"]
            if surv:
                end_lines.append("存活：" + "、".join(f"{s['名称']}（气血{s['气血']}/{s['气血上限']}）" for s in surv))
            if fled:
                end_lines.append("逃走：" + "、".join(fled))
            if dead:
                end_lines.append("败阵：" + "、".join(dead))
            if battle_slot is not None:
                rep = settle_battle(st, battle_slot)
                if rep:
                    end_lines.append("战后写回 .data（内力补满，气血保持）：" + "、".join(rep))
            exp_gain = adv.get("经验结算") or {}
            if exp_gain:
                end_lines.append("经验结算：" + "、".join(f"{n} +{v}" for n, v in exp_gain.items()))
            emit_battle_json(st, "\n".join(end_lines), winner=adv["战斗结束"],
                             my_side=my_side, turns=total,
                             end_mode=adv.get("结束方式"), end_side=adv.get("结束方"),
                             回合详情=flee_detail, 行动预告=pred)
            return
        PLAYER = st["当前行动者"]
        player_ui = render_player_prompt(st, skills_db, characters_db)
        action_info = build_player_action(st, skills_db, characters_db)
        emit_battle_json(st, report, player_ui=player_ui, my_side=my_side,
                         回合详情=flee_detail, 行动预告=pred, 行动信息=action_info)
        return

    # 认输指令：玩家方直接认输，敌方胜，按败方结算（不掷骰、不推进回合）
    if instruction.strip() in ("认输", "投降", "弃权"):
        my_side = _side_of(state, PLAYER)
        out = be.surrender(state, PLAYER)
        state = out["战场状态"]
        battle_slot = meta.get("slot")
        save_state(state, battle_slot)
        total = state.get("回合数", meta["n"])
        turn_text = render_turn(meta["n"] + 1, {"行动者": PLAYER, "指令": "认输"}, skills_db)
        lines = [turn_text, "",
                 f"**战斗结束 · {out['战斗结束']}胜（我方认输）**（共 {total} 回合）"]
        summary = state.get("状态摘要", [])
        surv = [s for s in summary if s.get("气血", 0) > 0]
        dead = [s["名称"] for s in summary if s.get("状态") == "败阵"]
        fled = [s["名称"] for s in summary if s.get("状态") == "逃走"]
        if surv:
            lines.append("存活：" + "、".join(f"{s['名称']}（气血{s['气血']}/{s['气血上限']}）" for s in surv))
        if fled:
            lines.append("逃走：" + "、".join(fled))
        if dead:
            lines.append("败阵：" + "、".join(dead))
        if battle_slot is not None:
            rep = settle_battle(state, battle_slot)
            if rep:
                lines.append("战后写回 .data（内力补满，气血保持）：" + "、".join(rep))
        exp_gain = out.get("经验结算") or {}
        if exp_gain:
            lines.append("经验结算：" + "、".join(f"{n} +{v}" for n, v in exp_gain.items()))
        sur_detail = [{"回合": meta["n"] + 1, "行动者": PLAYER, "类型": "认输",
                       "指令": "认输", "认输": True}]
        emit_battle_json(state, "\n".join(lines), winner=out["战斗结束"],
                         my_side=my_side, end_mode="认输", end_side=my_side, turns=total,
                         回合详情=sur_detail)
        return

    action, err = parse_player_input(instruction, state, skills_db, characters_db)
    my_side = _side_of(state, PLAYER)
    if err:
        report = f"无法执行：{err}"
        player_ui = render_player_prompt(state, skills_db, characters_db)
        action_info = build_player_action(state, skills_db, characters_db)
        emit_battle_json(state, report, player_ui=player_ui, my_side=my_side,
                         行动信息=action_info)
        return
    if action.get("类型") == "查看信息":
        info = render_char_info(state)
        player_ui = render_player_prompt(state, skills_db, characters_db)
        action_info = build_player_action(state, skills_db, characters_db)
        emit_battle_json(state, info, player_ui=player_ui, my_side=my_side,
                         行动信息=action_info)
        return
    out = be.auto_advance(state, action, PLAYER, set(players))
    results = out["结算列表"]
    state = out["战场状态"]
    pred = out.get("行动预告")
    text = render_results(results, skills_db, start_idx=meta["n"] + 1)
    details = render_results_struct(results, skills_db, start_idx=meta["n"] + 1,
                                    players=set(players))
    battle_slot = meta.get("slot")
    save_meta(meta["n"] + len(results), players, battle_slot, allow_escape=allow_escape)
    save_state(state, battle_slot)
    if out["战斗结束"]:
        total = state.get("回合数", meta["n"] + len(results))
        lines = [text]
        if text.strip():
            lines.append("")
        if out["战斗结束"] == "逃跑":
            lines.append(f"**战斗结束 · 逃跑**（共 {total} 回合）")
        else:
            lines.append(f"**战斗结束 · {out['战斗结束']}胜**（共 {total} 回合）")
        summary = state.get("状态摘要", [])
        surv = [s for s in summary if s.get("气血", 0) > 0]
        dead = [s["名称"] for s in summary if s.get("状态") == "败阵"]
        fled = [s["名称"] for s in summary if s.get("状态") == "逃走"]
        if surv:
            lines.append("存活：" + "、".join(f"{s['名称']}（气血{s['气血']}/{s['气血上限']}）" for s in surv))
        if fled:
            lines.append("逃走：" + "、".join(fled))
        if dead:
            lines.append("败阵：" + "、".join(dead))
        if battle_slot is not None:
            rep = settle_battle(state, battle_slot)
            if rep:
                lines.append("战后写回 .data（内力补满，气血保持）：" + "、".join(rep))
        exp_gain = out.get("经验结算") or {}
        if exp_gain:
            lines.append("经验结算：" + "、".join(f"{n} +{v}" for n, v in exp_gain.items()))
        emit_battle_json(state, "\n".join(lines), winner=out["战斗结束"],
                         my_side=my_side, turns=total,
                         end_mode=out.get("结束方式"), end_side=out.get("结束方"),
                         回合详情=details, 行动预告=pred)
        return
    PLAYER = state["当前行动者"]
    player_ui = render_player_prompt(state, skills_db, characters_db)
    action_info = build_player_action(state, skills_db, characters_db)
    emit_battle_json(state, text, player_ui=player_ui, my_side=my_side,
                     回合详情=details, 行动预告=pred, 行动信息=action_info)


def main():
    args = sys.argv[1:]
    player_arg = []
    seed = None
    teams_spec = None
    slot_arg = None
    allow_escape = None
    positionals = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--player":
            for n in args[i + 1].split(","):
                n = n.strip()
                if n:
                    player_arg.append(n)
            i += 2
            continue
        if a == "--seed":
            seed = int(args[i + 1])
            i += 2
            continue
        if a == "--teams":
            teams_spec = args[i + 1]
            i += 2
            continue
        if a == "--slot":
            # 正式游戏：数据从 slot 的 .data/ 工作副本读取
            slot_arg = int(args[i + 1])
            i += 2
            continue
        if a == "--允许逃跑":
            # 战前判定本场是否容许逃跑（必填，接收布尔值：true/false、是/否、1/0）
            val = args[i + 1].strip().lower()
            if val in ("true", "是", "1", "yes", "y"):
                allow_escape = True
            elif val in ("false", "否", "0", "no", "n"):
                allow_escape = False
            else:
                print("--允许逃跑 须接布尔值（true/false、是/否、1/0）", file=sys.stderr)
                return
            i += 2
            continue
        positionals.append(a)
        i += 1

    if slot_arg is not None:
        be.set_data_dir(slot_data_dir(slot_arg))

    if not positionals:
        print(__doc__)
        return

    faction_map = parse_teams(teams_spec) if teams_spec else None
    if faction_map:
        for name in faction_map:
            if name not in positionals:
                print(f"分队说明中的「{name}」不在参战角色里。参战角色：{'、'.join(positionals)}")
                return

    head = positionals[0]

    # 对战（开局交互战 start / 纯 AI）必须显式 --teams 指定分组，不再按门派默认分队
    SUBCMDS = {"go", "info", "stats"}
    if head == "start" or head not in SUBCMDS:
        if head == "start":
            combat_names = positionals[1:] if len(positionals) > 1 else DEFAULT_NAMES
        else:
            combat_names = positionals
        if not teams_spec:
            print("对战必须用 --teams 指定分组（不再按门派默认分队）。\n"
                  "例：--teams '朱如碧;和悦'  或  --teams '甲:朱如碧,余绮;乙:和悦,陈挺之'",
                  file=sys.stderr)
            return
        if allow_escape is None:
            print("对战必须用 --允许逃跑 <true|false> 指定本场是否允许逃跑（GM 战前据剧情人设判定）。",
                  file=sys.stderr)
            return
        missing = [n for n in combat_names if n not in faction_map]
        if missing:
            print(f"以下参战角色未在 --teams 中指定分组：{'、'.join(missing)}", file=sys.stderr)
            return

    # 子命令分支（玩家操控交互战）
    if head == "start":
        names = positionals[1:] if len(positionals) > 1 else DEFAULT_NAMES
        players = player_arg if player_arg else [resolve_player(names, None)]
        run_init(names, players, seed, faction_map, slot_arg, allow_escape=allow_escape)
        return
    if head == "go":
        if len(positionals) < 2:
            print("缺少指令。例：battle.py go '武学 天道三垣剑 朱如碧'")
            return
        run_step(" ".join(positionals[1:]), slot_arg)
        return
    if head == "info":
        state = load_state(slot_arg)
        info = render_char_info(state)
        my_side = _side_of(state, None)
        emit_battle_json(state, info, my_side=my_side)
        return
    if head == "stats":
        names = positionals[1:] if len(positionals) > 1 else [DEFAULT_PLAYER]
        show_stats(names)
        return

    # 无子命令 → 纯 AI 对战，所有位置参数均为角色名
    pure_ai(positionals, seed, faction_map, slot_arg, allow_escape=allow_escape)


if __name__ == "__main__":
    main()
