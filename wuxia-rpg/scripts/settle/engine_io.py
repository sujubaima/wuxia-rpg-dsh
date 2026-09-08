#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine io 层(由 engine.py 拆分)。"""
import os, sys
import copy
from common import dao as dq
from common.json_io import read_json
from store import save_manager as sm
from store import battle_runtime as br
from world import scene as sc
from store import explore_store as es
from store.battle_last import battle_last_path as _battle_last_path
from settle import engine_state as est

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


_MAP_PATH = os.path.join(HERE, "..", "assets", "data", "map.json")

_ASSETS_DIR = os.path.join(HERE, "..", "assets")

_DATA_ZIP = os.path.join(_ASSETS_DIR, "data.zip")

def _extract_zip_utf8(zf, dest):
    """解压 zip 到 dest，强制以 UTF-8 解码文件名。

    zipfile 默认按 cp437 解码非 ZIP64 扩展名，导致中文文件名变乱码。此处对每个条目取
    raw bytes（ptype=0 即未设 UTF-8 标志时 flag_bits & 0x800 为 0），按 UTF-8 重新解码后落盘，
    保证中文目录/文件名正确。
    """
    for info in zf.infolist():
        # 优先用 info.filename（已含 UTF-8 标志时即正确）；否则取原始字节按 UTF-8 解码
        if info.flag_bits & 0x800:
            name = info.filename
        else:
            name = info.orig_filename.encode("cp437").decode("utf-8")
        target = os.path.join(dest, *name.split("/"))
        if info.is_dir():
            os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())

def _ensure_data_dir():
    """若 assets/data 不存在则解压 assets/data.zip 到 assets/（得 assets/data/）。首次运行/迁移环境时初始化基线数据。"""
    if os.path.isdir(os.path.join(_ASSETS_DIR, "data")):
        return
    if not os.path.isfile(_DATA_ZIP):
        return
    import zipfile
    with zipfile.ZipFile(_DATA_ZIP) as zf:
        _extract_zip_utf8(zf, _ASSETS_DIR)

def _load_map():
    return read_json(_MAP_PATH, expected_type=dict)

def _resolve_region(name, nodes):
    """当前位置 → map.json 节点名。用已知节点集合做最长前缀匹配，取'区域·场景'的区域部分。
    支持区域名内部不含'·'（如'洞庭湖（岳阳）·岳阳楼' → '洞庭湖（岳阳）'）。"""
    if not name:
        return None
    if name in nodes:
        return name
    # 最长前缀匹配：pos==region 或 pos 以 region+'·' 开头
    best = None
    for r in nodes:
        if name == r or name.startswith(r + "·"):
            if best is None or len(r) > len(best):
                best = r
    return best

def _station_type(region, nodes_info):
    """取区域驿站类型。nodes_info 为 {区域: 驿站类型} dict（worldview 定义）。"""
    return nodes_info.get(region, "陆驿")

def _set_slot(slot):
    """重定向 dao 数据目录到 slot 的 .data/（写时复制：slot 优先 + 基线回退）。"""
    dq.set_slot(slot)

def _read_char(slot, name):
    # 事务态优先取暂存区（深拷贝，避免 apply 改动污染暂存），否则绕过缓存读盘取全新 dict
    if est._TXN is not None and name in est._TXN:
        return copy.deepcopy(est._TXN[name])
    return dq.read_character_file(name)

def _write_char(slot, name, char):
    # 仅暂存到事务区，待 settle 全部变更校验通过后由 commit 阶段统一刷盘（dq.update_char）。
    est._TXN[name] = char

def _party_status_row(slot, name):
    """取单个在队角色的状态行：名称/气血/内力/上限。
    气血内力经 dao.derive_character 派生（与战斗同源，含反哺/装备加成）。"""
    char = _read_char(slot, name)
    if not char:
        return {"名称": name}
    try:
        derived = dq.derive_character(char, dq.load_characters(), dq.load_skills())
    except (KeyError, TypeError):
        derived = char
    row = {
        "名称": name,
        "气血": derived.get("气血"),
        "气血上限": derived.get("气血上限"),
        "内力": derived.get("内力"),
        "内力上限": derived.get("内力上限"),
    }
    return row

def _build_state(slot):
    """结算后据角色文件 + explore.json 组装「当前状态」视图，供游历界面渲染。
    含：队伍状态行、金钱（主控铜钱）、位置、当前时间/时间/时段、状态提示、体力。"""
    _set_slot(slot)
    explore = es.get_all(slot)
    meta = sm.read_meta(slot) or {}
    player = meta.get("角色名")
    party = explore.get("队伍")
    # 玩家居首
    if isinstance(party, list) and player and party and party[0] != player and player in party:
        party = [player] + [n for n in party if n != player]

    rows = []
    if isinstance(party, list):
        for n in party:
            if isinstance(n, str) and n:
                rows.append(_party_status_row(slot, n))

    # 金钱：只取玩家主控铜钱（兼容旧档「银两」）
    money = 0
    if player:
        pc = _read_char(slot, player)
        if pc:
            money = pc.get("铜钱", pc.get("银两", 0)) or 0

    cur_time = explore.get("当前时间")

    # 当前地点的相邻场景（供 exploration-ui 周围情况渲染）：据「当前位置」的场景后缀
    # 取基线∪覆盖层的该场景方位出口。当前位置无场景后缀或未登记则该字段为空。
    adjacent = _adjacent_exits(explore.get("当前位置"), slot)
    # 当前场景功能类型（驿站/店铺/客栈，None=普通场景）：供前端据场景类型决定交互（如 商人 取值）
    cur_pos = explore.get("当前位置") or ""
    cur_region, _, cur_scene = cur_pos.partition("·")
    cur_scene_type = sc.scene_type(slot, cur_region, cur_scene)

    return {
        "队伍状态": rows,
        "金钱": money,
        "当前位置": explore.get("当前位置"),
        "当前时间": cur_time,
        "时间": sm.time_to_str(cur_time) if cur_time is not None else None,
        "时段": sm.time_slot_of(cur_time) if cur_time is not None else None,
        "状态提示": explore.get("状态提示"),
        "体力": explore.get("体力"),
        "相邻出口": adjacent,
        "当前场景类型": cur_scene_type,
    }

def _adjacent_exits(pos, slot):
    """据「区域·场景」格式的当前位置，返回该场景的方位出口列表
    [{方位, 邻场景}]（取基线∪覆盖层）；无场景后缀或未登记返回空列表。"""
    if not pos or "·" not in pos:
        return []
    region, _, scene = pos.partition("·")
    if not region or not scene:
        return []
    merged = sc.merged_scenes(slot, region)
    exits = merged.get(scene)
    if not exits:
        return []
    out = []
    for d in sc.COMPASS_ORDER:
        nb = exits.get(d)
        if nb:
            out.append({"方位": d, "邻场景": nb})
    return out

def _sync_party(slot, explore, party_changes):
    """据本轮成功的 在队 变更同步 explore.队伍，使 explore.json 队伍名单与角色「在队」字段一致。
    入队追加（玩家恒居首，非玩家追加末尾）、离队移除。玩家主控不因离队条目移除。"""
    player = (sm.read_meta(slot) or {}).get("角色名")
    party = list(explore.get("队伍") or [])
    for c in party_changes:
        name = c.get("角色")
        op = c.get("操作")
        if not name:
            continue
        if op == "入":
            if name not in party:
                party.append(name)
        elif op == "离":
            if name != player and name in party:
                party.remove(name)
    # 玩家居首
    if player and player in party and party[0] != player:
        party = [player] + [n for n in party if n != player]
    explore["队伍"] = party

def _prefix_role(c, r):
    """成功且带 角色 字段时，给 变更 补角色名前缀（如「叶瞬光 经验+102」）。"""
    if r.get("ok") and c.get("角色") and r.get("变更"):
        r["变更"] = f"{c['角色']} {r['变更']}"
    return r

def _resolve_party(slot):
    """解析当前在队名单（含玩家主控）：玩家恒在队，并取 explore.json 队伍列表。
    事务态下据 _TXN 中角色的 在队 字段覆写，反映本轮尚未落盘的入/离队，使批量校验生效。"""
    meta = sm.read_meta(slot) or {}
    player = meta.get("角色名")
    party = {player} if player else set()
    for n in es.get(slot, "队伍") or []:
        if n:
            party.add(n)
    party.discard(None)
    if est._TXN is not None:
        for name, ch in est._TXN.items():
            if name == player:
                continue
            if ch.get("在队"):
                party.add(name)
            else:
                party.discard(name)
    return party

def _derive_caps(ch):
    """取角色气血/内力上限（含武学/装备反哺，与队伍栏/战斗同源）。复用 dq.derived_overlay。"""
    ov = dq.derived_overlay(ch)
    if not ov:
        return ch.get("气血上限") or 0, ch.get("内力上限") or 0
    return ov.get("气血上限") or 0, ov.get("内力上限") or 0

def _clear_battle_tmp(slot):
    """清理该 slot 的战斗临时文件（battle_state/meta/report + battle_last 底稿）。战斗结束后由 judge 战后处置调用。"""
    # go 写入的战斗结算缓存（战斗-推进 底稿）
    try:
        os.remove(_battle_last_path(slot))
    except OSError:
        pass
    br.clear(slot)

