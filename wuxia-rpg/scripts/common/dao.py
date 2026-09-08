#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""武侠RPG 数据统一读写层（DAO）。

全引擎经本模块读写角色、武学、物品、状态与阵营数据，并取得角色派生视图。
本模块只提供库 API，不提供命令行入口；外部查询统一经 engine.py。

主要 API：
  set_data_dir(path) / set_slot(slot)
  list_names(kind) / get(kind, name) / get_many(kind, names) / get_field(kind, name, field)
  query_data(...) / query_setting(...) / recommend_wuxue(...)
  inventory(...) / skill_panel(...) / item_panel(...) / equip_panel(...)
  derived_overlay(name) / draft_npc(...)
  read_character_file(...) / write_character(...) / upsert(...) / delete(...)
"""
import os
import sys
import copy
import random

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
sys.path.insert(0, HERE)
from common import effect_loader as el  # 装备特效脚本加载（flat_bonuses），stdlib 实现，最基础层
from common.json_io import (
    JsonMissingError,
    JsonReadError,
    atomic_write_json,
    read_json,
    warn_json_read,
)

DATA_DIR = os.path.join(HERE, "..", "assets", "data")
# 存档根目录与 slot 路径约定（供 save_manager 等上层引用，避免上层各自维护路径）。
# 优先取环境变量 WUXIA_RPG_SAVE_DIR，否则默认 ~/.wuxia/save（用户主目录，跨项目共享、不随仓库移动）。
SAVE_DIR = os.environ.get("WUXIA_RPG_SAVE_DIR") or os.path.join(os.path.expanduser("~"), ".wuxia", "save")
SLOT_DATA_SUBDIR = ".data"


def slot_path(slot, save_dir=None):
    """返回 slot 号对应的目录路径（slot 可为 int 或 str）。"""
    return os.path.join(save_dir if save_dir is not None else SAVE_DIR, f"slot_{int(slot)}")


def slot_data_dir(slot, save_dir=None):
    """返回 slot 的 .data/ 工作副本目录路径。"""
    return os.path.join(slot_path(slot, save_dir), SLOT_DATA_SUBDIR)
# 冻结基线根：始终指向 assets/data/，永不随 set_data_dir 改动。
# 写时复制（copy-on-write）模式下，slot 的 .data/ 只存被改过的条目，
# 其余条目读取时透明回退到本基线，避免建档/读档时拷贝全部文件。
BASELINE_DATA_DIR = DATA_DIR
CHARACTERS_DIR = os.path.join(DATA_DIR, "characters")
SKILLS_DIR = os.path.join(DATA_DIR, "skills")
BUFFS_DIR = os.path.join(DATA_DIR, "buffs")
ITEMS_DIR = os.path.join(DATA_DIR, "items")
FACTIONS_DIR = os.path.join(DATA_DIR, "factions")

# kind → 子目录名
_KIND_SUBDIR = {
    "角色": "characters",
    "武学": "skills",
    "物品": "items",
    "状态": "buffs",
    "阵营": "factions",
}

TYPE_ALIASES = {
    "角色": "角色", "char": "角色", "characters": "角色", "character": "角色",
    "武学": "武学", "skill": "武学", "skills": "武学",
    "物品": "物品", "item": "物品", "items": "物品",
    "状态": "状态", "buff": "状态", "buffs": "状态",
    "阵营": "阵营", "faction": "阵营", "factions": "阵营",
}

# 缓存：{kind: {name: record}}，仅缓存当前 DATA_DIR 的读取；set_data_dir 失效。
_CACHE = {}
# load_all 内容缓存：{kind: {name: record}}，与 _SCAN_CACHE 同生命周期（_invalidate/set_data_dir 失效）。
_ALL_CACHE = {}
# 冻结基线扫描缓存：{kind: {name: path}}，基线不变故常驻、不随 set_data_dir 失效。
_BASELINE_SCAN_CACHE = {}


# ----------------------------- 目录重定向 -----------------------------

def set_data_dir(path):
    """将数据根目录重定向到 path（正式游戏用 slot 的 .data/ 工作副本）。

    覆盖 characters/skills/buffs/items/factions 五个子目录；清空读缓存。
    """
    global DATA_DIR, CHARACTERS_DIR, SKILLS_DIR, BUFFS_DIR, ITEMS_DIR, FACTIONS_DIR
    DATA_DIR = path
    CHARACTERS_DIR = os.path.join(path, "characters")
    SKILLS_DIR = os.path.join(path, "skills")
    BUFFS_DIR = os.path.join(path, "buffs")
    ITEMS_DIR = os.path.join(path, "items")
    FACTIONS_DIR = os.path.join(path, "factions")
    _invalidate()  # 失效扫描与记录缓存


def set_slot(slot):
    """重定向到存档 slot 的 .data/ 工作副本。"""
    set_data_dir(slot_data_dir(slot))


# 需按二级分组存放的类型：角色按门派、武学按类型、物品按品类；状态/阵营不分组。
_GROUPED = {"角色", "武学", "物品"}


def _group_for(kind, record):
    """计算条目所属二级分组名（仅对 _GROUPED 类型有意义）。"""
    if kind == "角色":
        return record.get("阵营") or "散人"
    if kind == "武学":
        return record.get("类型") or "其他"
    if kind == "物品":
        # 武器按子类型分目录（剑法装备/刀法装备/长兵装备/奇门装备/暗器装备/搏击装备）；
        # 秘籍按所授武学类型分（心法秘籍/剑法秘籍/…）；其余消耗品按子类型分（丹药/材料……）
        if record.get("类型") == "武器":
            wmap = {"剑": "剑法装备", "刀": "刀法装备", "长兵": "长兵装备",
                    "奇门": "奇门装备", "暗器": "暗器装备", "搏击": "搏击装备"}
            return wmap.get(record.get("子类型"), "装备")
        sub = record.get("子类型")
        return sub or record.get("类型") or "其他"
    return None


def _kind_base(kind, data_dir=None):
    """某类型的根目录：<data_dir>/<子目录>。"""
    base = data_dir if data_dir is not None else DATA_DIR
    return os.path.join(base, _KIND_SUBDIR[kind])


# 扫描缓存：{kind: {name: path}}，仅缓存当前 DATA_DIR；set_data_dir 失效。
_SCAN_CACHE = {}


def _index_path(base):
    """分组类型根目录下的索引文件路径。"""
    return os.path.join(base, "index.json")


def _read_index(base):
    """读 base/index.json；缺失回退扫描，损坏告警后回退扫描。"""
    idx = _index_path(base)
    try:
        data = read_json(idx, expected_type=dict)
    except JsonMissingError:
        return None
    except JsonReadError as exc:
        warn_json_read(exc)
        return None
    return {name: os.path.join(base, rel) for name, rel in data.items()}


def _scan_dir_raw(kind, base):
    """目录遍历扫描（内部用，不读 index），返回 {名称: 文件全路径}。

    分组类型：收集各二级子目录下的 <名>.json（兼容顶层散放的 .json）。
    非分组类型：收集顶层 <名>.json。跳过 index.json。
    """
    paths = {}
    if os.path.isdir(base):
        for entry in os.listdir(base):
            full = os.path.join(base, entry)
            if entry.endswith(".json"):
                if entry == "index.json":
                    continue
                paths[os.path.splitext(entry)[0]] = full
            elif os.path.isdir(full) and kind in _GROUPED:
                for fn in os.listdir(full):
                    if fn.endswith(".json"):
                        paths[os.path.splitext(fn)[0]] = os.path.join(full, fn)
    return paths


def _scan_dir(kind, base):
    """扫描单个根目录，返回 {名称: 文件全路径}。

    分组类型优先读 index.json（一次 JSON 读替代多级目录遍历）；无 index 或非分组类型
    则回退目录遍历。
    """
    if kind in _GROUPED:
        idx = _read_index(base)
        if idx is not None:
            return idx
    return _scan_dir_raw(kind, base)


def _maintain_index(kind, base, name, relpath_or_none):
    """写盘后维护 index.json：relpath_or_none 为相对路径则增改该条，为 None 则删除。
    仅当 base 已存在 index.json 时维护（无 index 则不创建，回退遍历仍正确）。
    """
    idx = _index_path(base)
    if not os.path.isfile(idx):
        return
    try:
        data = read_json(idx, expected_type=dict)
    except JsonMissingError:
        return
    except JsonReadError as exc:
        warn_json_read(exc)
        return
    if relpath_or_none is None:
        data.pop(name, None)
    else:
        data[name] = relpath_or_none
    atomic_write_json(idx, data, indent=2)


def _scan_kind(kind, data_dir=None):
    """扫描某类型目录，返回 {名称: 文件全路径}。

    data_dir 非 None：从指定根目录扫描，绕过缓存（绝对路径，不回退）。
    data_dir 为 None：用全局 DATA_DIR。
      - slot 模式（DATA_DIR ≠ 冻结基线）：写时复制——slot 优先 + 基线回退合并，
        slot 覆盖同名基线条目；结果按当前 DATA_DIR 缓存。
      - 调试模式（DATA_DIR == 基线）：仅扫描基线，行为不变。
    """
    if data_dir is not None:
        return _scan_dir(kind, _kind_base(kind, data_dir))
    if kind in _SCAN_CACHE:
        return _SCAN_CACHE[kind]
    slot_paths = _scan_dir(kind, _kind_base(kind, DATA_DIR))
    # slot 模式回退基线（冻结，可常驻缓存）
    if os.path.abspath(DATA_DIR) != os.path.abspath(BASELINE_DATA_DIR):
        base_paths = _baseline_scan(kind)
        merged = dict(base_paths)
        merged.update(slot_paths)  # slot 同名覆盖基线
        paths = merged
    else:
        paths = slot_paths
    _SCAN_CACHE[kind] = paths
    return paths


def _baseline_scan(kind):
    """扫描冻结基线某类型目录，结果常驻缓存（基线不变，无需失效）。"""
    cache = _BASELINE_SCAN_CACHE
    if kind in cache:
        return cache[kind]
    paths = _scan_dir(kind, _kind_base(kind, BASELINE_DATA_DIR))
    cache[kind] = paths
    return paths


def _invalidate(kind=None):
    """失效扫描与记录缓存。"""
    global _CHARACTERS_INDEX
    if kind is None:
        _SCAN_CACHE.clear()
        _CACHE.clear()
        _ALL_CACHE.clear()
        _CHARACTERS_INDEX = None  # 失效角色按需索引单例
    else:
        _SCAN_CACHE.pop(kind, None)
        _CACHE.pop(kind, None)
        _ALL_CACHE.pop(kind, None)
        if kind == "角色":
            _CHARACTERS_INDEX = None


# ----------------------------- 按需索引库 -----------------------------
# 懒加载封装：仅在访问具体条目时经 dao 读取单个文件，避免一次性全量载入。
# SkillIndex/CharacterIndex 提供 dict 风格 .get(name)/.names()，供派生、战斗、存档共用。

_CHARACTERS_INDEX = None


class SkillIndex:
    """武学技能按需索引：仅访问具体技能时经 dao 读取，不一次性载入全部技能。

    支持 dict 风格的 .get(name) 取值，与原 battle_engine.SkillIndex 接口兼容。
    """

    def __init__(self):
        self._cache = {}

    def _load_file(self, name):
        if name in self._cache:
            return self._cache[name]
        data = get("武学", name)
        self._cache[name] = data
        return data

    def get(self, name, default=None):
        """按技能名称获取详情（懒加载单个文件）。"""
        data = self._load_file(name)
        return default if data is None else data

    def names(self):
        """返回目录下所有技能名称（经 dao 取文件名，不载入详情）。"""
        return list_names("武学")


class CharacterIndex:
    """角色按需索引：仅访问具体角色时经 dao 读取，不一次性载入全部角色。

    支持 dict 风格的 .get(name) 取值，与原 battle_engine.CharacterIndex 接口兼容。
    """

    def __init__(self):
        self._cache = {}

    def _load_file(self, name):
        if name in self._cache:
            return self._cache[name]
        data = get("角色", name)
        self._cache[name] = data
        return data

    def get(self, name, default=None):
        """按角色名称获取详情（懒加载单个文件）。"""
        data = self._load_file(name)
        return default if data is None else data

    def names(self):
        """返回目录下所有角色名称（经 dao 取文件名，不载入详情）。"""
        return list_names("角色")


def load_skills():
    """返回武学技能的按需索引（SkillIndex，每次新建）。"""
    return SkillIndex()


def load_characters():
    """返回角色的按需索引（CharacterIndex 单例，随 set_data_dir 失效）。"""
    global _CHARACTERS_INDEX
    if _CHARACTERS_INDEX is None:
        _CHARACTERS_INDEX = CharacterIndex()
    return _CHARACTERS_INDEX


def character_path(name):
    """返回角色 JSON 全路径（扫描各门派子目录）；不存在返回 None。"""
    return _scan_kind("角色").get(name)


def _resolve_kind(token):
    """中文/英文别名 → 标准_kind；未知返回 None。"""
    if not token:
        return None
    k = TYPE_ALIASES.get(token.lower())
    if k:
        return k
    return TYPE_ALIASES.get(token)


# ----------------------------- 读 API -----------------------------

def _cache_for(kind):
    return _CACHE.setdefault(kind, {})


def _read_file(path):
    """严格读取权威数据记录；不存在或损坏均抛分类错误。"""
    return read_json(path, expected_type=dict)


def list_names(kind, data_dir=None):
    """返回某类型下全部名称列表（扫描各分组子目录，取 .json 文件名去后缀，按名排序）。

    data_dir 非 None 时从指定数据根目录列出（不影响缓存）。
    """
    return sorted(_scan_kind(kind, data_dir).keys())


def get(kind, name, data_dir=None):
    """取单条目 dict（带缓存）；不存在返回 None。

    data_dir 非 None 时绕过缓存、从指定数据根目录读取全新 dict。
    """
    if data_dir is not None:
        path = _scan_kind(kind, data_dir).get(name)
        return _read_file(path) if path else None
    cache = _cache_for(kind)
    if name in cache:
        return cache[name]
    path = _scan_kind(kind).get(name)
    rec = _read_file(path) if path else None
    cache[name] = rec  # None 也缓存，避免重复扫描
    return rec


def get_many(kind, names):
    """取多条目 list（按输入顺序，缺失项跳过且不提示）。"""
    return [r for r in (get(kind, n) for n in names) if r is not None]


def get_field(kind, name, field):
    """取单字段值；条目或字段缺失返回 (False, None)，成功返回 (True, value)。"""
    rec = get(kind, name)
    if rec is None or field not in rec:
        return False, None
    return True, rec[field]


def load_all(kind):
    """扫描某类目录（含分组子目录），合并为 {名称: 条目} dict。结果缓存，随 _invalidate/set_data_dir 失效。

    同时把读取的记录回填到单条缓存 _CACHE，使后续 get() 直接命中、免重读。
    """
    cached = _ALL_CACHE.get(kind)
    if cached is not None:
        return cached
    result = {}
    rec_cache = _cache_for(kind)
    for name, path in _scan_kind(kind).items():
        rec = _read_file(path)
        if rec and "名称" in rec:
            result[rec["名称"]] = rec
            rec_cache[rec["名称"]] = rec  # 回填单条缓存
    _ALL_CACHE[kind] = result
    return result


def read_character_file(name, data_dir=None):
    """原子读角色 JSON 为全新 dict（扫描门派子目录，不触碰缓存）；缺失返回 None。"""
    path = _scan_kind("角色", data_dir).get(name)
    return _read_file(path) if path else None


def inventory(name, data_dir=None):
    """角色背包聚合视图：[{名称, 数量, 类型, 子类型, 品级, 描述, 使用效果, 装备效果, 武学}, ...]。

    物品栏（角色「物品」list，重复条目代表堆叠）按出现顺序聚合计数，并附物品库定义的
    效果字段（消耗品「使用效果」/装备「装备效果」/秘籍「武学」）；物品定义缺失则仅保留
    名称与数量。供「查看背包」界面一次取全，免逐条查询物品。角色缺失返回 None。
    """
    char = get("角色", name, data_dir)
    if char is None:
        return None
    counts = {}
    order = []
    for it in char.get("物品") or []:
        nm = it if isinstance(it, str) else (it.get("名称") if isinstance(it, dict) else None)
        if not nm:
            continue
        if nm not in counts:
            order.append(nm)
            counts[nm] = 0
        counts[nm] += 1
    result = []
    for nm in order:
        entry = {"名称": f"`{nm}`", "数量": counts[nm]}
        rec = get("物品", nm, data_dir)
        if rec:
            for k in ("类型", "子类型", "品级", "描述", "使用效果", "装备效果"):
                if k in rec:
                    entry[k] = rec[k]
            if "武学" in rec:
                entry["武学"] = f"`{rec['武学']}`"
        result.append(entry)
    return result


def _skill_panel_entry(nm, level, data_dir=None):
    """单武学面板项：{名称, 等级, 类型, 目标范围, 威力倍率, 内力消耗, 冷却时间, 特效描述}。"""
    s = get("武学", nm, data_dir)
    entry = {"名称": f"`{nm}`", "等级": level}
    if s:
        for k in ("类型", "威力倍率", "内力消耗", "冷却时间"):
            if k in s:
                entry[k] = s[k]
        # 心法无目标选取，目标范围记「-」；主动武学缺省为单体
        entry["目标范围"] = "-" if s.get("类型") == "心法" else (s.get("目标范围") or "单体")
        if s.get("类型") == "心法" or s.get("技能特效"):
            entry["特效描述"] = effect_desc_of(s, level)
        else:
            entry["特效描述"] = "无"
    else:
        entry["特效描述"] = "（未找到武学定义）"
    return entry


def skill_panel(name, data_dir=None):
    """角色「更换武学」面板聚合视图：{运转心法, 携带武学, 可用主动武学}。

    - 运转心法：{名称, 等级, 特效描述}（无则 None）
    - 携带武学：list[{名称, 等级, 类型, 威力倍率, 内力消耗, 冷却时间, 特效描述}]（≤4，排除心法）
    - 可用主动武学：已习得且未携带、非心法的主动武学，同结构
    等级取角色「武学」字段记录；心法不计入携带。角色缺失返回 None。
    """
    char = get("角色", name, data_dir)
    if char is None:
        return None
    learned = {}
    for w in char.get("武学") or []:
        if isinstance(w, dict):
            learned[w.get("名称")] = max(1, w.get("等级", 1))
        elif isinstance(w, str):
            learned[w] = 1
    carried = char.get("携带技能") or []

    def is_xinfa(nm):
        s = get("武学", nm, data_dir)
        return bool(s and s.get("类型") == "心法")

    xinfa_name = char.get("运转心法")
    xinfa = None
    if xinfa_name:
        s = get("武学", xinfa_name, data_dir)
        xinfa = {"名称": f"`{xinfa_name}`", "等级": learned.get(xinfa_name, 1)}
        xinfa["特效描述"] = effect_desc_of(s, xinfa["等级"]) if s else "（未找到武学定义）"

    carried_list = []
    for nm in carried:
        if is_xinfa(nm):
            continue  # 心法不入携带展示
        carried_list.append(_skill_panel_entry(nm, learned.get(nm, 1), data_dir))

    carried_set = set(carried)
    available = []
    for nm, lv in learned.items():
        if nm in carried_set or is_xinfa(nm):
            continue
        available.append(_skill_panel_entry(nm, lv, data_dir))

    return {"运转心法": xinfa, "携带武学": carried_list, "可用主动武学": available}


def usable_in(item, scene, data_dir=None):
    """判断消耗品是否适用于指定场合（scene="战斗"|"世界"）。

    据物品「适用场合」字段（战斗/世界/通用）判断：战斗场合认「战斗」「通用」，
    世界场合认「世界」「通用」。无该字段的消耗品按子类型回退推断（丹药/道具→战斗，
    食物→世界），兼容旧数据。秘籍/技艺书等非「使用效果」类消耗品不在此判定。
    item 可为物品 dict 或名称 str（名称时查物品库）。
    """
    if isinstance(item, str):
        item = get("物品", item, data_dir)
    if not isinstance(item, dict) or item.get("类型") != "消耗品":
        return False
    occ = item.get("适用场合")
    if not occ:  # 兼容旧数据：无字段时按子类型回退
        sub = item.get("子类型") or ""
        if sub.endswith("秘籍") or sub == "技艺书":
            return False  # 秘籍/技艺书走研读/习艺，非场合类使用品
        occ = {"丹药": "战斗", "道具": "战斗", "食物": "世界"}.get(sub, "战斗")
    if scene == "战斗":
        return occ in ("战斗", "通用")
    if scene == "世界":
        return occ in ("世界", "通用")
    return False


def is_battle_consumable(item, data_dir=None):
    """判断物品是否为战斗可携带消耗品（据「适用场合」含战斗）。

    秘籍「类型」亦为「消耗品」但仅作大地图研读，不属战斗道具（无「适用场合」且子类型
    为「X秘籍」，usable_in 回退推断为战斗但秘籍无使用效果，实际不会进战斗携带）。
    """
    return usable_in(item, "战斗", data_dir)


def _consumable_panel_entry(nm, count, data_dir=None):
    """单战斗道具面板项：{名称, 数量, 子类型, 使用效果}。名称为纯名称，高亮由渲染层处理。"""
    rec = get("物品", nm, data_dir)
    entry = {"名称": nm, "数量": count}
    if rec:
        entry["子类型"] = rec.get("子类型")
        if "使用效果" in rec:
            entry["使用效果"] = rec["使用效果"]
    return entry


def item_panel(name, data_dir=None):
    """角色「更换道具」面板聚合视图：{携带道具, 可换道具}。

    仅战斗可携带消耗品（子类型 丹药/道具，排除秘籍）参与：
    - 携带道具：角色「携带物品」中属战斗消耗品的种类（按出现顺序），数量取物品栏实际持有数
    - 可换道具：物品栏中其它战斗消耗品（排除已携带）
    秘籍等非战斗物品一律不出现。角色缺失返回 None。
    """
    char = get("角色", name, data_dir)
    if char is None:
        return None
    bag = char.get("物品") or []
    counts = {}
    order = []
    for it in bag:
        nm = it if isinstance(it, str) else (it.get("名称") if isinstance(it, dict) else None)
        if not nm:
            continue
        if nm not in counts:
            order.append(nm)
            counts[nm] = 0
        counts[nm] += 1

    carried_raw = char.get("携带物品") or []
    carried_names = []
    seen = set()
    for it in carried_raw:
        nm = it if isinstance(it, str) else (it.get("名称") if isinstance(it, dict) else None)
        if nm and nm not in seen and is_battle_consumable(nm, data_dir):
            carried_names.append(nm)
            seen.add(nm)

    carried_list = [_consumable_panel_entry(nm, counts.get(nm, 0), data_dir) for nm in carried_names]

    carried_set = set(carried_names)
    available = []
    for nm in order:
        if nm in carried_set:
            continue
        if is_battle_consumable(nm, data_dir):
            available.append(_consumable_panel_entry(nm, counts[nm], data_dir))

    return {"携带道具": carried_list, "可换道具": available}


def is_equipment(item, data_dir=None):
    """判断物品是否为可装备物品（武器/护甲/冠巾/饰品）。item 可为 dict 或名称 str。"""
    if isinstance(item, str):
        item = get("物品", item, data_dir)
    if not isinstance(item, dict):
        return False
    return item.get("类型") in ("武器", "护甲", "冠巾", "饰品")


def equip_panel(name, data_dir=None):
    """角色「更换装备」面板聚合视图：{当前装备, 可换装备}。

    - 当前装备：{武器1, 武器2, 护甲, 饰品, 冠巾}，值为 {名称, 类型, 子类型, 品级} 或 None
      （武器附子类型如剑/刀/长兵/奇门/暗器，护甲/冠巾/饰品无子类型）
    - 可换装备：物品栏中可装备物品（武器/护甲/冠巾/饰品），按出现顺序去重，含名称/类型/子类型/品级/数量
      排除已装备在槽位的物品（同名牌不入可换）
    仅装备类物品参与，秘籍/丹药等一律排除。角色缺失返回 None。
    """
    char = get("角色", name, data_dir)
    if char is None:
        return None

    equipped = char.get("装备") or {}
    equipped_names = set()
    current = {}
    for slot in ("武器1", "武器2", "护甲", "饰品", "冠巾"):
        nm = equipped.get(slot)
        if not nm:
            current[slot] = None
            continue
        if isinstance(nm, dict):
            nm = nm.get("名称")
        equipped_names.add(nm)
        rec = get("物品", nm, data_dir) or {}
        current[slot] = {
            "名称": f"`{nm}`",
            "类型": rec.get("类型"),
            "子类型": rec.get("子类型"),
            "品级": rec.get("品级"),
        }

    counts = {}
    order = []
    for it in char.get("物品") or []:
        nm = it if isinstance(it, str) else (it.get("名称") if isinstance(it, dict) else None)
        if not nm:
            continue
        if nm not in counts:
            order.append(nm)
            counts[nm] = 0
        counts[nm] += 1

    available = []
    for nm in order:
        if nm in equipped_names:
            continue
        rec = get("物品", nm, data_dir)
        if not rec or rec.get("类型") not in ("武器", "护甲", "冠巾", "饰品"):
            continue
        entry = {"名称": f"`{nm}`", "数量": counts[nm], "类型": rec.get("类型"),
                  "子类型": rec.get("子类型"), "品级": rec.get("品级")}
        available.append(entry)

    return {"当前装备": current, "可换装备": available}


def derive_secondary(primary_attrs, polarities):
    """从一级属性和极性派生二级属性（属性派生唯一源，纯函数、仅依赖 stdlib）。

    战斗(battle_engine)/存档(save_manager)/人物创建(title-ui create-slot)三处同源调用本函数，
    保证二级属性口径一致；公式与极性修正见 wuxia-rpg-data-schema.md / wuxia-rpg-formulas.md。
    """
    neigong = primary_attrs["内功"]
    tizhi = primary_attrs["力道"]
    shenfa = primary_attrs["身法"]
    gengu = primary_attrs["根骨"]

    # 基础派生：(常数A + 系数B × 属性)；极性仅修正属性派生段，常数不受影响
    bases = {
        "气血上限": (250, 30, gengu, "气血"),
        "内力上限": (250, 30, neigong, "内力"),
        "攻击力": (25, 3, neigong, "攻击力"),
        "防御力": (25, 3, shenfa, "防御力"),
        "精准": (25, 3, tizhi, "精准"),
        "识破": (25, 3, gengu, "识破"),
        "速度": (25, 3, shenfa, "速度"),
        "暴击": (25, 3, tizhi, "暴击"),
    }
    exp_bonus = 0  # 经验加成(%)（悟性）基础值：默认0，由心法/装备等另行提供增益

    # 极性修正：同属性两极互为镜像（↑与↓对调），统一 ±20%
    polarity_map = {
        "内功": {"阳": {"攻击力": 0.2, "内力": -0.2}, "阴": {"内力": 0.2, "攻击力": -0.2}},
        "力道": {"刚": {"暴击": 0.2, "精准": -0.2}, "柔": {"精准": 0.2, "暴击": -0.2}},
        "身法": {"动": {"速度": 0.2, "防御力": -0.2}, "静": {"防御力": 0.2, "速度": -0.2}},
        "根骨": {"拙": {"气血": 0.2, "识破": -0.2}, "巧": {"识破": 0.2, "气血": -0.2}},
    }

    mods = {}
    for attr, pol in polarities.items():
        if pol != "中" and attr in polarity_map and pol in polarity_map[attr]:
            for k, v in polarity_map[attr][pol].items():
                mods[k] = mods.get(k, 0) + v

    # 公式：A + B × 属性 × (1 + 极性修正)，再取整（常数段不参与极性修正）
    derived = {"经验加成": exp_bonus,
               "休息气血恢复": 0.0,    # 休息时按气血上限的比例恢复气血（默认0）
               "休息内力恢复": 0.10}  # 休息时按内力上限的比例恢复内力（默认10%）
    for key, (a, b, attr_val, mod_key) in bases.items():
        derived[key] = round(a + b * attr_val * (1 + mods.get(mod_key, 0)))
    return derived


# ---------- 角色完整派生（武学反哺 + 装备加成） ----------
# 机制见 wuxia-rpg-formulas.md（武学有效值折算 / 修为反哺）；与 battle_engine 战斗期同源。

def get_learned_skills_with_level(char, characters_db=None):
    """返回 [(技能名, 等级), ...]，优先读角色自身 武学 字段，否则回退预设库。"""
    own = char.get("武学")
    if own:
        out = []
        for entry in own:
            if isinstance(entry, dict):
                out.append((entry.get("名称"), max(1, entry.get("等级", 1))))
            elif isinstance(entry, str):
                out.append((entry, 1))
        return out
    if characters_db:
        preset = characters_db.get(char.get("名称"))
        if preset and preset is not char:
            return get_learned_skills_with_level(preset, None)
    return []


# 武学等级增益：技能类修饰键作用于有效值（battle_engine.resolve_skill），角色类修饰键经修为反哺作用于武艺/二级属性。
_SKILL_MOD_KEYS = ("威力倍率", "内力消耗%", "冷却时间", "特效持续时间", "特效层数", "暴击倍率", "解锁特效", "特效增强")  # 特效增强为纯展示文案（mastery.fmt_effect），不参与反哺
_PRIMARY_KEYS = ("内功", "力道", "身法", "根骨")


def equipped_items(actor):
    """返回角色已装备物品的定义列表（按各栏位查物品库，跳过空栏与未知物品）。"""
    items_db = load_all("物品")
    out = []
    for slot in ("武器1", "武器2", "护甲", "饰品", "冠巾"):
        w = actor.get("装备", {}).get(slot)
        if not w:
            continue
        name = w if isinstance(w, str) else w.get("名称")
        info = items_db.get(name) if name else None
        if info:
            out.append(info)
    return out


def _iter_equipment_effects(actor):
    """遍历角色已装备物品的「装备效果」，yield (effect_module, params)。

    统一字段 装备效果 = {effect_id: params}，涵盖属性加成与特殊特效。
    """
    for item in equipped_items(actor):
        effects = item.get("装备效果") or {}
        if not isinstance(effects, dict):
            continue
        for eid, params in effects.items():
            mod = el.load_equipment_effect(eid)
            if mod is not None:
                yield mod, params


def collect_equipment_bonuses(actor):
    """汇总角色已装备物品的平坦属性加成：各脚本 flat_bonuses(actor, params) 返回值按属性求和。"""
    totals = {}
    for mod, params in _iter_equipment_effects(actor):
        fn = getattr(mod, "flat_bonuses", None)
        if callable(fn):
            for k, v in (fn(actor, params) or {}).items():
                totals[k] = totals.get(k, 0) + v
    return totals


def apply_equipment_bonuses(char):
    """装备平坦加成：把已装备物品的 武艺/二级属性 加成累加到角色。
    幂等（_装备已加成 标记保护）；需在二级属性派生之后调用。"""
    if char.get("_装备已加成"):
        return
    bonuses = collect_equipment_bonuses(char)
    if bonuses:
        wuyi_keys = ("搏击", "剑法", "刀法", "长兵", "奇门", "暗器")
        jiyi_keys = ("音律", "弈棋", "诗书", "绘画", "医术", "博物")
        wuyi = char.setdefault("武艺", {})
        sec = char.get("二级属性")
        for k, v in bonuses.items():
            if k in wuyi_keys:
                wuyi[k] = wuyi.get(k, 0) + v
            elif k in jiyi_keys:
                jiyi = char.setdefault("技艺", {})
                jiyi[k] = jiyi.get(k, 0) + v
            elif isinstance(sec, dict):
                sec[k] = sec.get(k, 0) + v
                if k == "气血上限":
                    char["气血上限"] = sec["气血上限"]
                    char["气血"] = min(char["气血上限"], char.get("气血", char["气血上限"]) + v)
                elif k == "内力上限":
                    char["内力上限"] = sec["内力上限"]
                    char["内力"] = min(char["内力上限"], char.get("内力", char["内力上限"]) + v)
    char["_装备已加成"] = True


def apply_mastery_bonuses(char, characters_db=None, skills_db=None):
    """修为反哺：把角色所习武学的 角色类 等级增益累加到 武艺 / 二级属性 / 一级属性。
    幂等：同一角色只施加一次（由 _修为已反哺 标记保护），不跨回合叠加。需在二级属性派生之后调用。

    skills_db 需由调用方传入（battle_engine.load_skills()）；一级属性反哺时先加到角色一级属性，
    再以更新后的一级属性 + 极性 重新派生二级属性，使增长经派生公式真正传导到攻防/速/上下限；
    重新派生引起的 气血上限/内力上限 增量同步补到当前气血/内力。
    """
    if char.get("_修为已反哺"):
        return
    learned = get_learned_skills_with_level(char, characters_db)
    wuyi_bonus = {}
    attr_bonus = {}
    primary_bonus = {}
    for name, level in learned:
        skill = skills_db.get(name) if skills_db else None
        if not skill:
            continue
        for entry in skill.get("等级增益", []):
            if not isinstance(entry, dict) or entry.get("等级", 1) > level:
                continue
            eff = entry.get("效果", {})
            for k, v in eff.items():
                if k == "武艺" and isinstance(v, dict):
                    for wk, wv in v.items():
                        wuyi_bonus[wk] = wuyi_bonus.get(wk, 0) + wv
                elif k in _SKILL_MOD_KEYS:
                    continue  # 技能类，不反哺角色
                elif k in _PRIMARY_KEYS:
                    primary_bonus[k] = primary_bonus.get(k, 0) + v
                else:
                    attr_bonus[k] = attr_bonus.get(k, 0) + v
    # 一级属性反哺：加到一级属性后重新派生二级属性
    if primary_bonus and "一级属性" in char and "极性" in char:
        prim = char["一级属性"]
        old_sec = char.get("二级属性", {})
        for k, v in primary_bonus.items():
            prim[k] = prim.get(k, 0) + v
        new_sec = derive_secondary(prim, char["极性"])
        for max_key, cur_key in (("气血上限", "气血"), ("内力上限", "内力")):
            delta = new_sec[max_key] - old_sec.get(max_key, new_sec[max_key])
            if delta > 0:
                char[cur_key] = min(new_sec[max_key], char.get(cur_key, new_sec[max_key]) + delta)
        char["二级属性"] = new_sec
        char["气血上限"] = new_sec["气血上限"]
        char["内力上限"] = new_sec["内力上限"]
    if wuyi_bonus:
        wuyi = char.setdefault("武艺", {})
        for k, v in wuyi_bonus.items():
            wuyi[k] = wuyi.get(k, 0) + v
    if attr_bonus and "二级属性" in char:
        sec = char["二级属性"]
        for k, v in attr_bonus.items():
            sec[k] = sec.get(k, 0) + v
            if k == "气血上限":
                char["气血上限"] = sec["气血上限"]
                cur = char.get("气血", char["气血上限"])
                char["气血"] = min(char["气血上限"], cur + v)
            elif k == "内力上限":
                char["内力上限"] = sec["内力上限"]
                cur = char.get("内力", char["内力上限"])
                char["内力"] = min(char["内力上限"], cur + v)
    char["_修为已反哺"] = True


def derive_character(char, characters_db=None, skills_db=None):
    """对单个角色 dict 完成完整属性派生，返回派生后的角色 dict（深拷贝，不改入参）。

    派生链：derive_secondary → 设满气血/内力 → apply_mastery_bonuses（武学反哺，含一级属性
    重派生）→ apply_equipment_bonuses（装备加成），再把战后带回的当前气血/内力夹到最新上限。
    与 battle.derive_char / query_data(..., derived=True) 同源，供不依赖 battle.py 的场合
    （如 save_manager 读档摘要）复刻派生上限。纯函数：深拷贝入参并清除幂等标记，可反复调用。
    skills_db 由调用方传入（battle_engine.load_skills()）；缺省则跳过武学反哺。"""
    c = copy.deepcopy(char)
    c.pop("_修为已反哺", None)
    c.pop("_装备已加成", None)
    c.pop("_心法已施展", None)
    carried_hp = c.get("气血")
    carried_mp = c.get("内力")
    c["二级属性"] = derive_secondary(c["一级属性"], c["极性"])
    c.setdefault("气血上限", c["二级属性"]["气血上限"])
    c.setdefault("内力上限", c["二级属性"]["内力上限"])
    c.setdefault("气血", c["气血上限"])
    c.setdefault("内力", c["内力上限"])
    apply_mastery_bonuses(c, characters_db, skills_db)
    apply_equipment_bonuses(c)
    if carried_hp is not None:
        c["气血"] = max(0, min(c["气血上限"], carried_hp))
    if carried_mp is not None:
        c["内力"] = max(0, min(c["内力上限"], carried_mp))
    return c


def derived_overlay(name_or_char):
    """角色战斗同源派生（基础派生 + 武学反哺 + 装备加成），返回追加字段 dict。
    含 气血上限/内力上限（含反哺，与战斗同源）。

    name_or_char：传角色名（str）→ 按名查预设/slot 角色派生；
                  传角色 dict → 直接用该 dict 派生（如 slot 运行时角色，含装备/武学变更）。
    直接复用本模块 derive_character（派生内核已下沉至 dao），无需 import battle，
    与「查看人物」/战斗内核同源；不改角色原始字段。"""
    c = name_or_char if isinstance(name_or_char, dict) else get("角色", name_or_char)
    if c is None:
        return None
    d = derive_character(c, load_characters(), load_skills())
    return {
        "二级属性": d["二级属性"],
        "气血上限": d["气血上限"],
        "内力上限": d["内力上限"],
        "武艺(含反哺与装备)": d.get("武艺", {}),
    }


# ----------------------------- 写 API -----------------------------

def _write_json(path, obj):
    atomic_write_json(path, obj, indent=2)


def _target_path(kind, name, record, data_dir=None):
    """计算条目落盘目标路径：分组类型入 <base>/<分组>/<名>.json，其余入 <base>/<名>.json。"""
    base = _kind_base(kind, data_dir)
    if kind in _GROUPED:
        return os.path.join(base, _group_for(kind, record), f"{name}.json")
    return os.path.join(base, f"{name}.json")


def _store(kind, record, data_dir=None):
    """通用落盘：写目标路径；若同名旧文件处于其他分组则先移除（支持分组迁移）。

    existing 仅在写入根目录内查找（slot 模式下不回退基线），避免回退拿到基线路径
    后误删冻结基线文件（写时复制下基线只读）。
    """
    name = record["名称"]
    target = _target_path(kind, name, record, data_dir)
    write_root = data_dir if data_dir is not None else DATA_DIR
    base = _kind_base(kind, write_root)
    existing = _scan_dir(kind, base).get(name)
    if existing and os.path.abspath(existing) != os.path.abspath(target):
        try:
            os.remove(existing)
        except OSError:
            pass
    _write_json(target, record)
    if kind in _GROUPED:
        _maintain_index(kind, base, name, os.path.relpath(target, base))
    if data_dir is None:
        _invalidate(kind)


def _normalize_character(record):
    """补齐可选字段缺省值，保证落盘/读取结构一致（避免下游 KeyError）。

    携带物品/物品/武学 缺省为 []；装备 缺省为 {}。已存在的非空值不动。
    携带技能 仅在缺省或为 None 时取武学名前 4 门补齐（战斗携带上限）——
    显式空列表视为有意卸空，不补齐。
    """
    if not isinstance(record, dict):
        return record
    for k in ("携带物品", "物品", "武学"):
        record.setdefault(k, [])
    record.setdefault("装备", {})
    record.setdefault("死亡", False)
    if record.get("携带技能") is None:
        record["携带技能"] = [w.get("名称") if isinstance(w, dict) else w
                              for w in record["武学"]][:4]
    return record


def write_character(name, record, data_dir=None):
    """将角色完整 dict 写入 <data_dir>/characters/<门派>/<名>.json（默认当前数据目录）。

    正式游戏由 save_manager 调用，data_dir 指向 slot 的 .data/。写后失效该类缓存。
    写前补齐可选字段缺省值，使 dao 输出与下游读取结构一致。

    重名校验：角色名须全局唯一（基线预设 + 当前写入域任意一处已存在即冲突），
    重名则抛 ValueError、不落盘。
    """
    record = _normalize_character(record)
    _check_name_unique("角色", name, data_dir)
    _store("角色", record, data_dir)


def update_char(name, record, data_dir=None):
    """更新已存在角色：与 write_character 相反，要求角色必须已存在于写入域，不存在则抛错、不落盘。
    存在则补齐缺省字段后整文件覆盖写（跳过重名校验——更新本就该重名）。写后失效该类缓存。
    data_dir 缺省当前数据目录；存在性仅在写入根目录内判定（不回退基线，与创建对称）。"""
    if read_character_file(name, data_dir) is None:
        raise ValueError(f"角色【{name}】不存在，无法更新（更新须先经 write-character 建号）")
    _store("角色", _normalize_character(record), data_dir)


# ----------------------------- 临时 NPC 快速构建 -----------------------------

# 基础四维单属性范围；实力等级 → 四维之和 = 4*(5+2*等级)，即平均 5+2*等级。
_NPC_ATTR_LO, _NPC_ATTR_HI = 5, 25


def _alloc_attrs(total, keys, lo, hi):
    """把 total 随机分配到各属性，保证每值 ∈ [lo,hi] 且和恰为 total（total 自动 clamp 到可行域）。"""
    n = len(keys)
    total = max(n * lo, min(n * hi, total))
    vals, remaining = [], total
    for i in range(n, 0, -1):
        # 当前槽取值后，剩余 i-1 个槽须各自能落在 [lo,hi]
        low = max(lo, remaining - (i - 1) * hi)
        high = min(hi, remaining - (i - 1) * lo)
        v = random.randint(low, high)
        vals.append(v)
        remaining -= v
    random.shuffle(vals)
    return dict(zip(keys, vals))


def draft_npc(name, persona, faction, level):
    """快速起草临时 NPC 角色模板（不落盘）：据 姓名/人设/阵营/实力等级 生成最小可用角色 dict 返回。

    实力等级为整数：基础四维之和 = 4*(5+2*等级)，在 [5,25] 内随机分配到 内功/力道/身法/根骨；
    等级超出 [0,10] 时四维之和被 clamp 到 [20,100]（即全 5 或全 25）。武艺以平均四维为基准加
    随机偏移。极性默认"中"、武学/装备/物品留空。仅返回模板供引擎调整；正式落盘经
    engine.py judge 的「写角色」状态变更条目完成。
    """
    if not name:
        raise ValueError("姓名不能为空")
    try:
        level = int(level)
    except (TypeError, ValueError):
        raise ValueError("实力等级须为整数")
    total = 4 * (5 + 2 * level)
    total = max(4 * _NPC_ATTR_LO, min(4 * _NPC_ATTR_HI, total))
    keys = ("内功", "力道", "身法", "根骨")
    attrs = _alloc_attrs(total, keys, _NPC_ATTR_LO, _NPC_ATTR_HI)
    avg = total // 4  # 平均四维，作为武艺基准
    martial = {k: max(1, min(_NPC_ATTR_HI, avg + random.randint(-3, 2)))
               for k in ("搏击", "剑法", "刀法", "长兵", "奇门", "暗器")}
    return {
        "id": name,
        "名称": name,
        "性别": "男",
        "年龄": 30,
        "阵营": faction or "散人",
        "一级属性": attrs,
        "极性": {k: "中" for k in attrs},
        "武艺": martial,
        "技艺": {"音律": 2, "弈棋": 2, "诗书": 2, "绘画": 2, "医术": 2, "博物": 2},
        "人设": persona or "",
        "经验值": 0,
        "武学": [],
        "携带技能": [],
        "装备": {"武器1": None, "武器2": None, "护甲": None, "饰品": None, "冠巾": None},
        "物品": [],
        "关系度": 50,
        "死亡": False,
        "战斗风格": "勇猛",
    }


# ----------------------------- 武学/装备推荐 -----------------------------

# 主动武学类型 → 对应武器装备目录（心法无对应装备，不在此表）
_WUXUE_PREF_TYPES = {"剑法", "刀法", "长兵", "奇门", "暗器", "搏击"}
_WUXUE_TO_EQUIP_DIR = {"剑法": "剑法装备", "刀法": "刀法装备", "长兵": "长兵装备",
                       "奇门": "奇门装备", "暗器": "暗器装备", "搏击": "搏击装备"}


def _is_jianghu(faction):
    """江湖阵营判定：散人/无门派（None/空/散人/江湖）算江湖，具体门派名不算。"""
    return (faction or "").strip() in ("", "散人", "江湖")


def recommend_wuxue(name, faction, attrs, preference):
    """据 阵营/一级属性/武学偏好 推荐 武学+心法+装备，返回 {"心法":[], "武学":[], "装备":[]}（名称列表）。

    实力等级由一级属性内部换算：(一级属性之和 - 20) // 8。
    一级属性（attrs）为 {内功, 力道, 身法, 根骨} 四维 dict。
    武学偏好（preference）须为六种主动武学类型之一：剑法/刀法/长兵/奇门/暗器/搏击。
    实力等级 → 品级上界：<=5 取 0-1 品；>5 取 0-2 品（武学/心法同此）。
    装备始终取 0-1 品，且仅匹配偏好类型对应的武器目录。

    候选源：
      · 江湖阵营（散人/无门派）→ 从所有武学中按偏好类型筛；
      · 非江湖阵营（门派弟子）→ 先从本门武学中筛该类型；本门无该类型武学则 fallback 到所有武学。
        心法同此规则（类型=心法）。姓名仅作标识，不参与筛选。
    每项候选若超过 6 门，则从中随机选 6 门返回。
    """
    if preference not in _WUXUE_PREF_TYPES:
        raise ValueError(f"武学偏好须为 {_WUXUE_PREF_TYPES} 之一，收到【{preference}】")
    level = _level_from_attrs(attrs)
    grade_hi = 1 if level <= 5 else 2

    all_skills = load_all("武学")  # {名称: rec}
    jianghu = _is_jianghu(faction)
    faction_skill_names = set()
    if not jianghu:
        fac = get("阵营", faction)
        if fac:
            faction_skill_names = set(fac.get("武学") or [])

    def _pick(skill_type):
        """按类型选候选源并过品级，返回名称列表（按品级升序、名称排序）。"""
        if jianghu:
            pool = all_skills
        else:
            # 本门武学中该类型；本门无该类型则 fallback 全集
            in_faction = {n: r for n, r in all_skills.items() if n in faction_skill_names
                          and r.get("类型") == skill_type}
            pool = in_faction if in_faction else all_skills
        picks = [n for n, r in pool.items()
                 if r.get("类型") == skill_type and _grade_le(r.get("品级"), grade_hi)]
        return _sort_by_grade(picks, all_skills)

    武学 = _pick(preference)
    心法 = _pick("心法")

    # 装备：仅偏好类型对应武器目录，品级固定 0-1
    equip_dir = _WUXUE_TO_EQUIP_DIR[preference]
    all_items = load_all("物品")
    装备 = [n for n, r in all_items.items()
            if r.get("类型") == "武器" and _group_for("物品", r) == equip_dir
            and _grade_le(r.get("品级"), 1)]
    装备 = _sort_by_grade(装备, all_items)

    return {"心法": _brief_list(_cap_random(心法, 6), "武学"),
            "武学": _brief_list(_cap_random(武学, 6), "武学"),
            "装备": _brief_list(_cap_random(装备, 6), "物品")}


def _brief_list(names, kind):
    """名称列表 → 简表列表（每项 {名称, 品级, 描述}），按列表顺序。武学/装备通用。"""
    out = []
    for n in names:
        rec = get(kind, n)
        if rec is None:
            out.append({"名称": n, "品级": None, "描述": ""})
            continue
        out.append({"名称": n, "品级": rec.get("品级"), "描述": rec.get("描述", "")})
    return out


def _level_from_attrs(attrs):
    """一级属性 {内功,力道,身法,根骨} → 实力等级 = (四维之和 - 20) // 8。"""
    if not isinstance(attrs, dict):
        raise ValueError("一级属性须为 {内功,力道,身法,根骨} dict")
    try:
        total = sum(int(attrs[k]) for k in ("内功", "力道", "身法", "根骨"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("一级属性须含 内功/力道/身法/根骨 四项整数")
    return (total - 20) // 8


def _cap_random(names, cap):
    """候选超过 cap 门时随机选 cap 门返回（保持原顺序，随机抽样）；否则原样返回。"""
    if len(names) <= cap:
        return names
    idx = sorted(random.sample(range(len(names)), cap))
    return [names[i] for i in idx]


def _grade_le(grade, hi):
    """品级 <= hi 判定（品级缺失/非整数视为不通过）。"""
    try:
        return 0 <= int(grade) <= hi
    except (TypeError, ValueError):
        return False


def _sort_by_grade(names, source):
    """按 (品级, 名称) 升序；品级缺失排末尾。"""
    def key(n):
        g = source.get(n, {}).get("品级")
        try:
            return (0, int(g), n)
        except (TypeError, ValueError):
            return (1, 0, n)
    return sorted(names, key=key)


# ----------------------------- 设定查询 -----------------------------

def _persona_text(char):
    """取角色人设文本并加 500 空格前导（防工具调用返回时剧透），缺省返回空串。"""
    p = char.get("人设")
    p = p.strip() if isinstance(p, str) and p else ""
    return (" " * 500 + p) if p else ""


def _desc_text(desc):
    """门派描述加 500 空格前导（防剧透），缺省返回空串。"""
    d = desc.strip() if isinstance(desc, str) and desc else ""
    return (" " * 500 + d) if d else ""


def _member_brief(name, data_dir=None):
    """成员简表：{名称, 人设, 死亡}。角色缺失记 死亡=null、人设空。"""
    c = get("角色", name, data_dir=data_dir)
    if c is None:
        return {"名称": name, "人设": "", "死亡": None}
    return {"名称": name, "人设": _persona_text(c), "死亡": bool(c.get("死亡", False))}


def _skill_brief(name, data_dir=None):
    """武学简表：{名称, 类型, 品级, 描述}。武学缺失仅记名称。"""
    s = get("武学", name, data_dir=data_dir)
    if s is None:
        return {"名称": name}
    return {"名称": name, "类型": s.get("类型"), "品级": s.get("品级"), "描述": s.get("描述", "")}


def query_setting(target, data_dir=None):
    """快捷查询设定：传入门派或人物，聚合返回设定信息（供 GM 编排前核实）。

    · 传入门派名（在阵营数据中）：返回
        {"类型":"门派","门派":{名称/描述/地理位置/武学},"成员":[{名称,人设,死亡}, ...]}
    · 传入人物名：返回
        {"类型":"人物","人物":{名称,阵营,人设,死亡,预设},"门派":<门派设定或"江湖散人">}
        所属阵营在阵营数据中 → 附门派设定（名称/描述/地理位置/武学）；
        阵营无对应文件（如「散人」）→ "门派":"江湖散人"。
        预设：角色是否在冻结基线 assets/data/ 中（True=预设角色，False=GM自创/存档新增）。
    · 既非门派也非人物：返回 {"错误":"未找到【target】"}。
    data_dir 缺省读当前 DATA_DIR（slot 模式下即 slot 的 .data/，基线回退）。
    """
    faction = get("阵营", target, data_dir=data_dir)
    if faction is not None:
        return {
            "类型": "门派",
            "门派": {
                "名称": faction.get("名称"),
                "描述": _desc_text(faction.get("描述")),
                "地理位置": faction.get("地理位置"),
                "武学": [_skill_brief(n, data_dir=data_dir) for n in faction.get("武学", [])],
            },
            "成员": [_member_brief(n, data_dir=data_dir) for n in faction.get("成员", [])],
        }
    char = get("角色", target, data_dir=data_dir)
    if char is not None:
        side = char.get("阵营")
        faction = get("阵营", side, data_dir=data_dir) if side else None
        return {
            "类型": "人物",
            "人物": {
                "名称": char.get("名称"),
                "阵营": side,
                "人设": _persona_text(char),
                "死亡": bool(char.get("死亡", False)),
                "预设": target in _baseline_scan("角色"),
            },
            "门派": ({
                "名称": faction.get("名称"),
                "描述": _desc_text(faction.get("描述")),
                "地理位置": faction.get("地理位置"),
                "武学": [_skill_brief(n, data_dir=data_dir) for n in faction.get("武学", [])],
            } if faction is not None else "江湖散人"),
        }
    return {"错误": f"未找到【{target}】。若为GM自创NPC，请先以 engine.py judge 的「写角色」状态变更条目落盘再引用"}


def _check_name_unique(kind, name, data_dir=None):
    """重名校验：基线预设 + 当前写入域任意一处已存在该名即抛错。
    所有类型（角色/武学/物品/状态/阵营）一律不得重名落盘。"""
    if (name in _baseline_scan(kind)
            or name in _scan_kind(kind, data_dir)):
        raise ValueError(f"{kind}名【{name}】已存在，不得重名落盘")


def upsert(kind, record, data_dir=None):
    """通用写入：按 record["名称"] 落盘单文件 JSON（分组类型入对应子目录）。
    重名校验：基线预设 + 当前写入域任意一处已存在该名即抛错、不落盘（对所有类型生效）。"""
    _check_name_unique(kind, record["名称"], data_dir)
    _store(kind, record, data_dir)


def delete(kind, name, data_dir=None):
    """删除某条目文件（仅在写入根目录内定位，不回退基线）；不存在则无动作。"""
    write_root = data_dir if data_dir is not None else DATA_DIR
    base = _kind_base(kind, write_root)
    path = _scan_dir(kind, base).get(name)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    if kind in _GROUPED:
        _maintain_index(kind, base, name, None)
    if data_dir is None:
        _invalidate(kind)


def build_index(data_dir=None, kinds=None):
    """为分组类型（角色/武学/物品）在 data_dir 下生成 index.json：{名称: 相对路径}。
    data_dir 缺省为当前 DATA_DIR；kinds 缺省为全部 _GROUPED。返回 {kind: 条目数}。
    供基线 assets/data 一次性建索引；运行时 _scan_dir 读它替代目录遍历。
    """
    root = data_dir if data_dir is not None else DATA_DIR
    targets = kinds if kinds else list(_GROUPED)
    out = {}
    for kind in targets:
        base = _kind_base(kind, root)
        paths = _scan_dir_raw(kind, base)  # 原始遍历，忽略既有 index
        rels = {name: os.path.relpath(p, base) for name, p in paths.items()}
        atomic_write_json(_index_path(base), rels, indent=2)
        out[kind] = len(rels)
    _invalidate()  # 刷新扫描缓存，使新 index 生效
    return out

# ----------------------------- 技能特效说明生成 -----------------------------
# 把技能特效转成一句话「纯机制」描述（原 effect_describe 模块并入）。
# 静态属性取自 effects/skills/<名>.py 的 EFFECT_* 常量（经 el.load_skill_effect）；
# 等级相关部分（持续时间/解锁门控）从武学「等级增益」表实时折算，
# 口径与 battle_engine.resolve_skill 一致。

def _eff_applicable(skill, level):
    """等级≤level 的十境条目（稠密/稀疏表兼容）。委托 effect_loader，单一折算源。"""
    return el._eff_applicable(skill, level)


def _eff_dur_bonus(skill, level):
    """describe_skill_effect 用：取指定 level 的特效持续时间加成。"""
    return sum(e.get("效果", {}).get("特效持续时间", 0) for e in el._eff_applicable(skill, level))


def _eff_gate_level(skill):
    """「解锁特效」所在等级；十境表无该键返回 None（特效始终在线）。"""
    for e in skill.get("等级增益", []):
        if isinstance(e, dict) and e.get("效果", {}).get("解锁特效"):
            return e.get("等级")
    return None


_STATUS_BRIEF_CACHE = None


def _status_brief(status_id):
    """状态 id → 「【名】（效果）」；效果取 buffs 的「效果」字段。"""
    global _STATUS_BRIEF_CACHE
    if _STATUS_BRIEF_CACHE is None:
        _STATUS_BRIEF_CACHE = {b.get("id"): b for b in load_all("状态").values()}
    b = _STATUS_BRIEF_CACHE.get(status_id)
    if not b:
        return f"【{status_id}】"
    name = b.get("名称", status_id)
    eff = b.get("效果", "")
    return f"【{name}】" + (f"（{eff}）" if eff else "")


def describe_skill_effect(effect_name, skill, level=1):
    """生成某技能特效在指定等级的一句话说明（纯机制）。

    effect_name: 武学「技能特效」字段值（如 glamour_dazzle）；空或缺失脚本返回 ""。
    skill:       武学 dict（读其「等级增益」折算十境）。
    level:       武学精进等级（默认 1）。
    """
    if not effect_name:
        return ""
    mod = el.load_skill_effect(effect_name)
    if mod is None:
        return ""

    status = getattr(mod, "EFFECT_STATUS", None)
    if not status:
        # 非状态类：脚本声明的机制文案 + 当前等级已生效的「特效增强」（十境表）附加于后
        out = getattr(mod, "EFFECT_MECHANIC", "") or ""
        jx_parts = [e.get("效果", {}).get("特效增强")
                    for e in _eff_applicable(skill, level)
                    if isinstance(e, dict) and e.get("效果", {}).get("特效增强")]
        jx_parts = [j for j in jx_parts if j]
        if jx_parts:
            out += ("；" if out else "") + "；".join(jx_parts)
        return out

    base = getattr(mod, "EFFECT_DURATION", 1) or 1
    target = getattr(mod, "EFFECT_TARGET", "target")
    lead = getattr(mod, "EFFECT_MECHANIC", "")  # 额外前置机制（如辛酉的「必中」）
    dur = base + _eff_dur_bonus(skill, level)

    if target == "self":
        who = "自身施加"
    elif target == "allies_self":
        who = "为全体队友（含自身）施加"
    else:
        who = "施加"

    # 状态简述默认取 buff「效果」字段（不随等级变）；skill_effect 脚本可声明
    # effect_brief(skill, level) 覆盖之，使简述随等级变（如满境封禁品级扩展）。
    if hasattr(mod, "effect_brief"):
        brief = mod.effect_brief(skill, level) or _status_brief(status)
    else:
        brief = _status_brief(status)
    base_stacks = getattr(mod, "EFFECT_STACKS", 1) or 1
    stacks = base_stacks + sum(e.get("效果", {}).get("特效层数", 0) for e in el._eff_applicable(skill, level))
    layer = f"{stacks}层" if stacks > 1 else ""
    # 触发时机：脚本实现 on_action 者用「出招后」；否则按识破类型区分。
    if hasattr(mod, "on_action"):
        lead_hit = "出招后"
    elif skill.get("识破类型") == "无":
        lead_hit = "命中即（无需识破）"
    else:
        lead_hit = "命中后"
    body = f"{lead_hit}{who}{layer}{dur}回合{brief}"

    gl = _eff_gate_level(skill)
    if gl is not None and level < gl:
        # 当前等级未解锁特效 → 无特效
        return ""
    out = (lead + body) if lead else body
    # 当前等级已生效的「特效增强」（十境表）附加于后（与 xinfa_effect 同口径）
    jx_parts = [e.get("效果", {}).get("特效增强")
                for e in _eff_applicable(skill, level)
                if isinstance(e, dict) and e.get("效果", {}).get("特效增强")]
    jx_parts = [j for j in jx_parts if j]
    if jx_parts:
        out += "；" + "；".join(jx_parts)
    return out


def xinfa_unlock_at(skill, level):
    """该境界新解锁的心法效果项说明列表（解锁等级 == level 的项）。
    用于十境表在对应境显示其解锁的运转特效；无则返回空列表。"""
    out = []
    for e in skill.get("心法效果") or []:
        if not isinstance(e, dict):
            continue
        if e.get("解锁等级") == level:
            sid = e.get("施加状态")
            if sid:
                out.append(_status_brief(sid))
    return out


def xinfa_effect(skill, level=1):
    """心法「心法效果」字段 → 一句话；空返回 ""。

    心法效果为运转时长效施加的状态列表：[{"施加状态": <id>, "解锁等级"?: N}, ...]。
    带 解锁等级 的项仅在当前精进等级 ≥ 该境时显示（与 apply_xinfa_statuses 同口径）。
    当前等级已生效的「特效增强」（十境表）附加于后；未达等级不显示。
    """
    effects = skill.get("心法效果") or []
    status_parts = []
    for e in effects:
        if not isinstance(e, dict):
            continue
        gate = e.get("解锁等级")
        if gate and (level or 1) < gate:
            continue  # 未达境界门控，不显示该项
        sid = e.get("施加状态")
        if sid:
            status_parts.append(_status_brief(sid))
    jx_parts = [e.get("效果", {}).get("特效增强")
                for e in _eff_applicable(skill, level)
                if isinstance(e, dict) and e.get("效果", {}).get("特效增强")]
    jx_parts = [j for j in jx_parts if j]
    if not status_parts and not jx_parts:
        return ""
    out = ""
    if status_parts:
        out += "运转时施加" + "、".join(status_parts)
    if jx_parts:
        out += ("；" if out else "") + "；".join(jx_parts)
    return out


def describe_wuxue(skill_name, level=1, data_dir=None):
    """按武学名取其特效说明；无特效或未找到返回 ""。

    心法优先取「心法效果」长效状态描述，为空再回退「技能特效」。
    """
    skill = get("武学", skill_name, data_dir=data_dir)
    if not skill:
        return ""
    if skill.get("类型") == "心法":
        desc = xinfa_effect(skill, level)
        if desc:
            return desc
    return describe_skill_effect(skill.get("技能特效", ""), skill, level)


def effect_desc_of(skill, level=1):
    """武学技能特效的一句话描述（供 CLI 输出 _特效描述）。

    心法优先取「心法效果」长效状态描述，为空再回退「技能特效」。
    """
    try:
        if skill.get("类型") == "心法":
            desc = xinfa_effect(skill, level)
            if desc:
                return desc
        return describe_skill_effect(skill.get("技能特效", ""), skill, level) or "无"
    except Exception as e:
        return f"（生成失败：{e}）"


def query_data(kind, names=None, derived=False, fields=None, level=1):
    """结构化基础查询，供 engine/tool 复用；不负责切换 slot。

    返回统一对象 ``{类型, 结果, ...}``。名称为空时列出该类型全部名称；
    单名返回对象/标量，多名返回数组。查询语义与原 CLI 保持一致。
    """
    kind = _resolve_kind(kind)
    if not kind:
        return {"错误": "未知类型；可用：角色 / 武学 / 物品 / 状态 / 阵营"}

    if names is None:
        names = []
    elif isinstance(names, str):
        names = [names]
    elif not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        return {"错误": "名称须为字符串或字符串数组"}
    names = [n.strip() for n in names if n.strip()]

    if fields is None:
        fields = []
    elif isinstance(fields, str):
        fields = [f.strip() for f in fields.split(",") if f.strip()]
    elif not isinstance(fields, list) or any(not isinstance(f, str) for f in fields):
        return {"错误": "字段须为字符串或字符串数组"}
    else:
        fields = [f.strip() for f in fields if f.strip()]

    try:
        level = int(level)
    except (TypeError, ValueError):
        return {"错误": "等级须为整数"}

    if not names:
        all_names = list_names(kind)
        return {"类型": kind, "数量": len(all_names), "结果": all_names}

    not_found = []
    entries = []
    raw_entries = []
    for name in names:
        entry = get(kind, name)
        if entry is None:
            not_found.append(name)
            continue
        raw = dict(entry)
        out = dict(entry)
        if kind == "武学":
            desc = effect_desc_of(entry, level)
            raw["_特效描述"] = desc
            out["_特效描述"] = desc
        raw_entries.append((name, raw))
        if kind == "阵营" and isinstance(out.get("描述"), str):
            out["描述"] = " " * 500 + out["描述"]
        if kind == "角色":
            out.pop("人设", None)
            out["预设"] = name in _baseline_scan("角色")
            if derived:
                try:
                    out["_派生(战斗同源)"] = derived_overlay(name)
                except FileNotFoundError:
                    out["_派生(战斗同源)"] = "（派生失败：角色文件不存在）"
        entries.append(out)

    errors = []
    if not_found:
        errors.append("未找到" + kind + "【" + "、".join(not_found) + "】")

    if fields:
        values = []
        missing = []
        for name, entry in raw_entries:
            if len(fields) > 1:
                item = {}
                for field in fields:
                    if field not in entry:
                        missing.append(f"【{name}】无字段「{field}」")
                        continue
                    value = entry[field]
                    if (field == "人设" or (kind == "阵营" and field == "描述")) \
                            and isinstance(value, str):
                        value = " " * 500 + value
                    item[field] = value
                values.append(item)
            else:
                field = fields[0]
                if field not in entry:
                    missing.append(f"【{name}】无字段「{field}」")
                    continue
                value = entry[field]
                if (field == "人设" or (kind == "阵营" and field == "描述")) \
                        and isinstance(value, str):
                    value = " " * 500 + value
                values.append(value)
        errors.extend(missing)
        result = values[0] if len(names) == 1 and values else values
    else:
        result = entries[0] if len(names) == 1 and entries else entries

    payload = {"类型": kind, "结果": result}
    if fields:
        payload["字段"] = fields
    if errors:
        payload["错误"] = "；".join(errors)
    return payload
