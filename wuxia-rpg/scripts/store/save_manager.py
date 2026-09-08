#!/usr/bin/env python3
"""武侠RPG 存档管理器 —— 按角色 slot 分目录，写时复制 .data/ + 字段级增量存档。

存档根目录:   环境变量 WUXIA_RPG_SAVE_DIR 指定，未设则默认 ~/.wuxia/save（用户主目录）
角色 slot:    {存档根}/slot_{N}/  （N 递增，每次新建角色占用一个 slot）
工作副本:     save/slot_{N}/.data/  （写时复制：只存被改过的条目，其余读取时透明回退冻结基线 assets/data/）
slot 元信息:  save/slot_{N}/meta.json  （角色名、创建时间、最近存档、存档数）
实时镜像:     save/slot_{N}/explore.json  （GM 维护部分的持久镜像：经历概括/任务摘要及进度/队伍/状态提示/当前位置/当前时间/体力；角色数值归 .data/ 不在此）
存档文件:     save/slot_{N}/savefile_{YYYYMMDD_HHMMSS}.json
保留上限:     每个 slot 最多 5 个存档（超出时删除时间戳最早的一个）

## 写时复制（copy-on-write）

- slot 的 `.data/` **不再全量拷贝** assets/data/：建档/读档只建空目录 + 写入有变更的条目，
  其余条目读取时由 dao 透明回退冻结基线 `assets/data/`（见 dao._scan_kind 回退逻辑）。
- 写入（explore settle / battle 战后）只 patch 有变更的角色文件落 slot，基线只读、绝不污染
  （dao._store 的 existing 查找限定在写入根目录内，不回退基线）。
- 收益：建档/读档从逐文件拷贝 684 个文件（~24s）降到接近 0。

## explore.json（实时状态镜像）

- 每个 slot 常驻，是 GM 内存 state 的持久副本（镜像），只存 GM 维护字段；角色数值仍由 .data/ 管理。
- **由 `scripts/engine.py go` 托管**：GM 每回合结尾调 settle（stdin 传叙事状态 + 变更条目），
  settle 固化数据变动后，非存档回合全量写 explore.json（含经历概括），存档回合由 save 全量同步。
- `restore` 读档后全量把存档叙事字段同步回 explore.json，并重置计数器。
- 查看任务统一读 explore.json：`read-tasks <N>` 取 任务摘要及进度（含已完成+未完成）；
  `read-history <N>` 取 过往经历。
- 字段集：经历概括/任务摘要及进度/队伍/状态提示/当前位置/当前时间/体力（「行为」为 settle 必传输入，不落盘）。
- `checkpoint`/`write_explore` 接口仍保留作底层，但 GM 主路径已统一到 engine.py go。

## 数据模型

- **正式游戏**所有数据从 slot 的 `.data/` 读取（引擎 `--slot <N>` 将数据目录重定向到
  `save/slot_{N}/.data`）；`.data/` 经 dao 回退基线 `assets/data/`，被改条目落 slot、未改条目读基线。
- **模拟调试**不带 `--slot`，直接读原始 `assets/data/`。
- 玩家创建的角色写入 `.data/characters/<门派>/<角色名>.json`（不放入原始 `assets/data/`）。

## 存档（字段级增量，脚本自动 diff）

- `save`：GM 传入叙事状态（经历概括/任务摘要），脚本自动比对 slot `.data/characters`
  与冻结基线 `assets/data/characters` 生成字段级增量 `人物状态`，写入存档。GM 无需手动追踪字段。
- `restore`（读档）：清空 slot `.data/`（仅删 slot 写过的条目，不重拷基线），再把存档的 `人物状态`
  增量相对冻结基线按一层深合并后写入 slot。GM 无需手动合并。
- 增量相对**冻结基线 assets/data/**，故多存档可独立回滚：每份存档都能从 assets/data/ 重建其时刻状态。

可通过命令行调用，也可作为模块导入
（create_slot/restore/save/write_character/load/list_slots/list_saves/prune/latest/write_explore/read_explore/read_tasks/read_history/checkpoint）。
"""
import json
import os
import random
import re
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
sys.path.insert(0, HERE)
from common import dao as dq
from common import time_utils as ut
from common.json_io import (
    JsonMissingError,
    JsonReadError,
    JsonSchemaError,
    atomic_write_json,
    read_json,
    warn_json_read,
)

DEFAULT_SAVE_DIR = dq.SAVE_DIR
_NPC_SPAWN = None


def _load_npc_spawn():
    """加载预设角色初始位置映射（assets/data/npc_spawn.json），缓存。"""
    global _NPC_SPAWN
    if _NPC_SPAWN is None:
        path = os.path.join(dq.BASELINE_DATA_DIR, "npc_spawn.json")
        data = read_json(path, expected_type=dict)
        _NPC_SPAWN = {k: v for k, v in data.items() if k != "_说明"}
    return _NPC_SPAWN

DEFAULT_DATA_DIR = dq.DATA_DIR
DEFAULT_CHARACTERS_DIR = os.path.join(DEFAULT_DATA_DIR, "characters")
SKILL_MD = os.path.join(os.path.dirname(HERE), "SKILL.md")
MAX_SAVES_PER_SLOT = 5
TIMESTAMP_FMT = "%Y%m%d_%H%M%S"
SLOT_RE = re.compile(r"^slot_(\d+)$")
FILENAME_RE = re.compile(r"^savefile_(\d{8}_\d{6})(?:_(\d+))?\.json$")
META_FILENAME = "meta.json"
DATA_SUBDIR = dq.SLOT_DATA_SUBDIR
EXPLORE_FILENAME = "explore.json"  # slot 常驻实时状态镜像（GM 维护部分），存档前定稿、读档后同步
MERCHANT_FILENAME = "merchant.json"  # 商人货架缓存（{"区域-地点-卖家名":{"库存":{...},"上架时间":N}}），随存档保存/读档恢复
MERCHANT_KEY = "merchant_cache"  # 存档 payload 顶层键名


def _mkdir_slot(slot, save_dir=DEFAULT_SAVE_DIR):
    """创建槽位目录。"""
    os.makedirs(slot_path(slot, save_dir), exist_ok=True)


def _merchant_path(slot, save_dir=DEFAULT_SAVE_DIR):
    return os.path.join(slot_path(slot, save_dir), MERCHANT_FILENAME)


def read_merchant_cache(slot, save_dir=DEFAULT_SAVE_DIR):
    """读 merchant.json；缺失返回 {}，损坏告警后重建。旧平铺格式自动弃置。"""
    path = _merchant_path(slot, save_dir)
    try:
        data = read_json(path, expected_type=dict)
    except JsonMissingError:
        return {}
    except JsonReadError as exc:
        warn_json_read(exc)
        return {}
    # 旧格式 key 为纯卖家名（不含「-」），与新「区域-地点-卖家名」语义不同，直接丢弃，
    # 对应货架取数时按无记录重新生成
    return {k: v for k, v in data.items() if "-" in k}


def write_merchant_cache(slot, data, save_dir=DEFAULT_SAVE_DIR):
    """写 merchant.json（保证 slot 目录存在）；data 为空 dict 时删除文件以保持整洁。"""
    if not _slot_writable(slot):
        return
    path = _merchant_path(slot, save_dir)
    if not data:
        if os.path.isfile(path):
            os.remove(path)
        return
    _mkdir_slot(slot, save_dir)
    atomic_write_json(path, data, indent=2)


def _load_merchant_cache(target, slot, save_dir=DEFAULT_SAVE_DIR, payload=None):
    """读取存档顶层「货架缓存」；字段缺失（旧存档）回退当前 merchant.json 内容。"""
    path = _resolve_save_path(target, slot, save_dir)
    payload = _read_save_payload(path) if payload is None else payload
    cache = payload.get(MERCHANT_KEY)
    if cache is None:
        return read_merchant_cache(slot, save_dir)
    if not isinstance(cache, dict):
        raise JsonSchemaError(path, f"{MERCHANT_KEY} 须为对象")
    # 同 read_merchant_cache：弃置旧格式 key（纯卖家名，不含「-」）
    return {k: v for k, v in cache.items() if "-" in k}


# 场景图覆盖层（GM 运行时新增场景，scene.py 为权威读写者，此处仅作 save/restore 同步镜像）
MAP_OVERLAY_FILENAME = "map_overlay.json"
MAP_OVERLAY_KEY = "map_overlay"  # 存档 payload 顶层键名

# 场景类型覆盖层（GM 运行时新增场景的功能类型：驿站/店铺/客栈，scene.py 权威读写，save/restore 同步镜像）
SCENE_TYPES_OVERLAY_FILENAME = "scene_types_overlay.json"
SCENE_TYPES_OVERLAY_KEY = "scene_types_overlay"  # 存档 payload 顶层键名


def read_map_overlay(slot, save_dir=DEFAULT_SAVE_DIR):
    """读 map_overlay.json；缺失返回 {}，存在但损坏时拒绝降级。"""
    path = os.path.join(slot_path(slot, save_dir), MAP_OVERLAY_FILENAME)
    try:
        return read_json(path, expected_type=dict)
    except JsonMissingError:
        return {}


def write_map_overlay(slot, data, save_dir=DEFAULT_SAVE_DIR):
    """写 map_overlay.json（保证 slot 目录存在）；data 为空 dict 时删除文件以保持整洁。"""
    if not _slot_writable(slot):
        return
    path = os.path.join(slot_path(slot, save_dir), MAP_OVERLAY_FILENAME)
    if not data:
        if os.path.isfile(path):
            os.remove(path)
        return
    _mkdir_slot(slot, save_dir)
    atomic_write_json(path, data, indent=2)


def read_scene_types_overlay(slot, save_dir=DEFAULT_SAVE_DIR):
    """读 scene_types_overlay.json；缺失返回 {}，存在但损坏时拒绝降级。"""
    path = os.path.join(slot_path(slot, save_dir), SCENE_TYPES_OVERLAY_FILENAME)
    try:
        return read_json(path, expected_type=dict)
    except JsonMissingError:
        return {}


def write_scene_types_overlay(slot, data, save_dir=DEFAULT_SAVE_DIR):
    """写 scene_types_overlay.json（保证 slot 目录存在）；data 为空 dict 时删除文件以保持整洁。"""
    if not _slot_writable(slot):
        return
    path = os.path.join(slot_path(slot, save_dir), SCENE_TYPES_OVERLAY_FILENAME)
    if not data:
        if os.path.isfile(path):
            os.remove(path)
        return
    _mkdir_slot(slot, save_dir)
    atomic_write_json(path, data, indent=2)


def _load_scene_types_overlay(target, slot, save_dir=DEFAULT_SAVE_DIR, payload=None):
    """读取存档顶层「场景类型覆盖层」；字段缺失（旧存档）回退当前覆盖层。"""
    path = _resolve_save_path(target, slot, save_dir)
    payload = _read_save_payload(path) if payload is None else payload
    overlay = payload.get(SCENE_TYPES_OVERLAY_KEY)
    if overlay is None:
        return read_scene_types_overlay(slot, save_dir)
    if not isinstance(overlay, dict):
        raise JsonSchemaError(path, f"{SCENE_TYPES_OVERLAY_KEY} 须为对象")
    return overlay


def _load_map_overlay(target, slot, save_dir=DEFAULT_SAVE_DIR, payload=None):
    """读取存档顶层「场景图覆盖层」；字段缺失（旧存档）回退当前覆盖层。"""
    path = _resolve_save_path(target, slot, save_dir)
    payload = _read_save_payload(path) if payload is None else payload
    overlay = payload.get(MAP_OVERLAY_KEY)
    if overlay is None:
        return read_map_overlay(slot, save_dir)
    if not isinstance(overlay, dict):
        raise JsonSchemaError(path, f"{MAP_OVERLAY_KEY} 须为对象")
    return overlay


def _read_version():
    """从 SKILL.md frontmatter 读取 version 字段，失败回退 '0.0.0'。存档时写入实时版本号。"""
    try:
        with open(SKILL_MD, encoding="utf-8") as f:
            head = f.read(2048)
        m = re.search(r"^version:\s*([^\s]+)", head, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return "0.0.0"
# 新角色初入大世界时由 create-slot 自动写入的初始存档 label 与叙事 state
INITIAL_LABEL = "初入江湖"
# 落点候选：worldview.md 第二节「游戏区域」开放地区清单，剔除不宜开局区域（如幽冥宫、东洋海岛、关外）
OPEN_REGIONS = [
    "苏州城", "杭州城", "泉州港", "南洋海岛", "长沙城", "九嶷山",
    "巫山", "武当山", "成都城", "峨眉山", "大理", "五瘴林", "洛阳城", "嵩山",
    "华山", "崆峒山", "北京城", "昆仑山",
]
# 时间换算（time_to_str / time_slot_of / 常量）统一在 time_utils，此处透传复用
TIME_UNITS_PER_DAY = ut.TIME_UNITS_PER_DAY
time_to_str = ut.time_to_str
time_slot_of = ut.time_slot_of


def _random_location_time():
    """随机抽取落点大区域与起始时刻（第一天 0~95），供 create-slot 自动初始化。
    返回 (位置, 时刻数字)。"""
    region = random.choice(OPEN_REGIONS)
    t = random.randint(0, TIME_UNITS_PER_DAY - 1)  # 第一天 0~95
    return region, t


def ensure_dir(save_dir=DEFAULT_SAVE_DIR):
    """存档目录不存在时自动创建"""
    os.makedirs(save_dir, exist_ok=True)


def _now_timestamp():
    return datetime.now().strftime(TIMESTAMP_FMT)


# ----------------------------- slot 维度 -----------------------------

def slot_path(slot, save_dir=DEFAULT_SAVE_DIR):
    """返回 slot 号对应的目录路径（slot 可为 int 或 str）。转发 dao 的路径约定。"""
    return dq.slot_path(slot, save_dir)


def slot_data_dir(slot, save_dir=DEFAULT_SAVE_DIR):
    """返回 slot 的 .data/ 工作副本目录路径。转发 dao 的路径约定。"""
    return dq.slot_data_dir(slot, save_dir)


def next_slot_number(save_dir=DEFAULT_SAVE_DIR):
    """扫描已有 slot_* 目录，返回下一个 slot 号（max+1，无则 1）"""
    if not os.path.isdir(save_dir):
        return 1
    max_n = 0
    for fn in os.listdir(save_dir):
        m = SLOT_RE.match(fn)
        if m and os.path.isdir(os.path.join(save_dir, fn)):
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def read_meta(slot, save_dir=DEFAULT_SAVE_DIR):
    """读取 slot 的 meta.json；不存在返回 None，存在但损坏时拒绝降级。"""
    path = os.path.join(slot_path(slot, save_dir), META_FILENAME)
    try:
        return read_json(path, expected_type=dict)
    except JsonMissingError:
        return None


def write_meta(slot, meta, save_dir=DEFAULT_SAVE_DIR):
    """写入 slot 的 meta.json"""
    if not _slot_writable(slot):
        return
    path = os.path.join(slot_path(slot, save_dir), META_FILENAME)
    atomic_write_json(path, meta, indent=2)


# explore.json 仅存 GM 维护字段（角色数值归 .data/，不在此）
EXPLORE_KEYS = ("经历概括", "任务摘要及进度", "队伍", "状态提示",
                "当前位置", "当前时间", "体力", "当前剧情", "场景要素", "人物位置")

# 体力（队伍资源）：初值/上限均为 100，写入时夹取 [0, STAMINA_MAX]
STAMINA_MAX = 100

# 行为（settle 必传输入字段，仅本轮分类用，不落盘、不存读档）：
# GM 把玩家指令归入下列一项或多项传入；每项为 {"类型": ..., ...参数} 对象。
# normalize_behavior 做去重与校验，保留 类型 外的参数（如 休息 的 时长）。
# 取值：观察交谈/远行（徒步）/远行（乘舟车）/当前地点内运动/触发战斗/休息/其他
BEHAVIOR_TYPES = ("观察交谈", "远行（徒步）", "远行（乘舟车）", "当前地点内运动", "触发战斗", "休息", "其他")

# 行为→体力消耗（多项行为累加）；settle 据此自动扣体力并记入结算状态变化栏。
# 休息/远行（乘舟车） 不消耗体力、反而补满（settle 特判处理，不在此表）
BEHAVIOR_STAMINA_COST = {
    "观察交谈": 1,
    "远行（徒步）": 10,
    "当前地点内运动": 5,
    "触发战斗": 20,
    "其他": 5,
}

# 行为→时间消耗（刻，多项行为累加；1 时辰 = 8 刻）。settle 据此自动推进当前时间。
# 休息 时长由 GM 经 行为.时长（刻）传入，不在此表
# 远行（乘舟车） 固定推进 1 天（96 刻），不在此表
BEHAVIOR_TIME_COST = {
    "观察交谈": 1,
    "远行（徒步）": 8,
    "当前地点内运动": 2,
    "触发战斗": 8,
    "其他": 2,
}

# 乘车移动：固定消耗
RIDE_TIME_COST = TIME_UNITS_PER_DAY  # 1 天 = 96 刻


def normalize_behavior(raw):
    """归一「行为」字段为对象数组：每项 {"类型": ..., ...参数}。

    接受单个对象或对象数组；去重保序、按 BEHAVIOR_TYPES 校验 类型，
    保留 类型 外的参数（如 休息 的 时长）。
    返回合法对象数组（非空）或 None（缺失/全非法/类型非法/非对象）。"""
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    seen, cleaned = set(), []
    for it in raw:
        if not isinstance(it, dict):
            continue
        t = it.get("类型")
        if isinstance(t, str) and t in BEHAVIOR_TYPES and t not in seen:
            seen.add(t)
            params = {k: v for k, v in it.items() if k != "类型"}
            cleaned.append({"类型": t, **params})
    return cleaned if cleaned else None


def behavior_types(behavior):
    """从归一后的行为对象数组取出 类型 集合。"""
    return {b.get("类型") for b in behavior if isinstance(b, dict)}


def behavior_param(behavior, btype, key, default=None):
    """从归一后的行为对象数组中取指定 类型 行为的某参数。"""
    for b in behavior:
        if isinstance(b, dict) and b.get("类型") == btype:
            return b.get(key, default)
    return default


def _explore_path(slot, save_dir=DEFAULT_SAVE_DIR):
    return os.path.join(slot_path(slot, save_dir), EXPLORE_FILENAME)


def read_explore(slot, save_dir=DEFAULT_SAVE_DIR):
    """读取 explore.json；不存在返回 {}，存在但损坏时拒绝降级。
    读取时自动修正「当前位置」区域名，兼容旧存档写法。"""
    path = _explore_path(slot, save_dir)
    try:
        data = read_json(path, expected_type=dict)
    except JsonMissingError:
        return {}
    if data.get("当前位置"):
        data["当前位置"] = _fix_region(data["当前位置"])
    return data


# 旧区域名（带「城/港」或括号说明）→ map.json 节点名。山门类（武当山等）本就带山，无需在此。
_REGION_FIX = {
    "苏州城": "苏州", "杭州城": "杭州", "泉州港": "泉州", "长沙城": "长沙",
    "成都城": "成都", "洛阳城": "洛阳", "北京城": "北京", "金陵（南京）": "金陵", "金陵(南京)": "金陵",
}

# 旧区域名（内部含'·'）→ 新区域名（内部用全角括号）迁移映射。
# 旧格式「岳阳·洞庭湖·岳阳楼」需按旧区域名前缀整体替换为「洞庭湖（岳阳）·岳阳楼」。
_REGION_DOT_MIGRATE = {
    "岳阳·洞庭湖": "洞庭湖（岳阳）",
    "西安·关中": "关中（西安）",
    "河西·兰州": "河西（兰州）",
}


def _fix_region(pos):
    """修正「当前位置」的区域部分为 map.json 节点名；「·」后具体地点保留。
    兼容旧区域名（内部含'·'，如'岳阳·洞庭湖'）迁移到新名（'洞庭湖（岳阳）'）。"""
    if not isinstance(pos, str):
        return pos
    # 旧区域名迁移：旧区域名作前缀整体替换
    for old, new in _REGION_DOT_MIGRATE.items():
        if pos == old:
            return new
        if pos.startswith(old + "·"):
            return new + pos[len(old):]   # 保留场景后缀
    if "·" not in pos:
        return _REGION_FIX.get(pos, pos)
    region, _, detail = pos.partition("·")
    region = _REGION_FIX.get(region, region)
    return f"{region}·{detail}" if detail else region


# 过往经历为存档定稿内容，GM 实时写 explore.json 时须保持不变，
# 仅在 save/restore 同步时随存档更新
# 实时回合保留现值、仅存档路径覆盖的字段（经历概括已改为每回合直接落盘，此处暂留空）
NARRATIVE_PRESERVE_KEYS = ()


def _slot_writable(slot):
    """slot 可写性：slot<=0 为「未选存档」哨兵（前端 currentSlot 默认 0），永远不该落盘——
    避免门厅列档等只读请求误触发写入创建垃圾 slot_0。所有写盘入口统一经此把关。"""
    try:
        return int(slot) > 0
    except (TypeError, ValueError):
        return False


def _normalize_event_node(n):
    """节点归一为字典形态 {描述, 奖励?}。接受字符串（纯描述）或字典。"""
    if isinstance(n, str):
        return {"描述": n}
    if isinstance(n, dict):
        node = {"描述": n.get("描述", "")}
        if n.get("奖励") is not None:
            node["奖励"] = n["奖励"]
        return node
    return {"描述": ""}


def _normalize_event(e):
    """事件归一：进展节点统一为字典形态。"""
    if not isinstance(e, dict):
        return e
    if "进展节点" in e and isinstance(e["进展节点"], list):
        e = dict(e)
        e["进展节点"] = [_normalize_event_node(n) for n in e["进展节点"]]
    return e


def merge_events(existing, incoming):
    """按 名称 增量合并事件列表：incoming 中匹配 existing 的整体替换、不匹配的新增，
    existing 中未被 incoming 提及的事件保留。无 名称 字段者视为新增直接追加。

    事件以名称为键整体替换——GM 传入某事件即应含其完整进展节点列表，整体覆盖该事件。
    进展节点统一归一为字典形态 {描述, 奖励?}（字符串节点自动转换）。纯函数，不依赖存档 IO。
    """
    merged = list(existing)
    index = {}
    for i, e in enumerate(merged):
        if isinstance(e, dict) and "名称" in e:
            index[e["名称"]] = i
    for e in incoming:
        e = _normalize_event(e)
        name = e.get("名称") if isinstance(e, dict) else None
        if name is not None and name in index:
            merged[index[name]] = e
        else:
            merged.append(e)
            if name is not None:
                index[name] = len(merged) - 1
    return merged


def write_explore(slot, data, save_dir=DEFAULT_SAVE_DIR, preserve_narrative=True):
    """写入 slot 的 explore.json。仅保留 GM 维护字段，其余忽略；状态提示不在此填充（存档时 GM 填）。

    preserve_narrative=True（GM 实时写入，默认）：经历概括一律保留 explore.json
        现值（仅 save/restore 更新）；其余字段按输入更新。
    preserve_narrative=False（save/restore 同步）：按输入完整更新经历概括
        等字段（全量替换）；事件（任务摘要及进度）也整体覆盖——读档须恢复到存档点
        的线索全集，不能与实时回合累积的现值增量合并（否则存档点之后新增的线索删不掉）。
    preserve_narrative=True（GM 实时写入，默认）：事件按 名称 增量合并（匹配整体替换、
        不匹配新增、未提及保留），GM 只传本轮变动的事件即可。
    """
    data = data if isinstance(data, dict) else {}
    if not _slot_writable(slot):
        return
    explore = {k: data[k] for k in EXPLORE_KEYS if k in data}
    # 体力写入前夹取 [0, STAMINA_MAX]，杜绝越界存盘
    if "体力" in explore:
        try:
            explore["体力"] = max(0, min(STAMINA_MAX, int(explore["体力"])))
        except (TypeError, ValueError):
            explore.pop("体力", None)
    existing = read_explore(slot, save_dir)
    if preserve_narrative:
        # 经历概括为存档定稿内容，实时回合一律保留现值（不论是否传入），仅在 save/restore 更新
        for k in NARRATIVE_PRESERVE_KEYS:
            if k in existing:
                explore[k] = existing[k]
            else:
                explore.pop(k, None)
        # 实时回合：事件按 名称 增量合并（匹配整体替换、不匹配新增、未提及保留），
        # GM 只传本轮变动的事件即可。
        explore["任务摘要及进度"] = merge_events(
            existing.get("任务摘要及进度") or [], explore.get("任务摘要及进度") or []
        )
    else:
        # save/restore：事件整体覆盖，恢复到存档点线索全集（避免与现值增量合并导致后续线索删不掉）
        if "任务摘要及进度" in explore:
            explore["任务摘要及进度"] = list(explore["任务摘要及进度"] or [])
    # 人物位置：运行时状态。_apply_changes 已增量写入（如 `抵达`/`写角色`），
    # 未涉及的按 npc_spawn 基线补全（key=角色名，value=区域名）。
    pos = dict(explore.get("人物位置") or {})
    for name, loc in _load_npc_spawn().items():
        if name not in pos:
            pos[name] = loc
    explore["人物位置"] = pos
    # round 为独立持久字段（不属 GM 叙事输入），写叙事时透传保留现有值
    if "round" in existing:
        explore["round"] = existing["round"]
    # 体力为跨回合资源：GM 本轮未传入时保留现有值（GM 传入则覆盖，含置 0）；保留时一并夹取上限
    if "体力" not in explore and "体力" in existing:
        try:
            explore["体力"] = max(0, min(STAMINA_MAX, int(existing["体力"])))
        except (TypeError, ValueError):
            pass
    # 当前位置/当前时间/队伍：实时回合未传入时保留现有值（GM 不再每回合传，由 抵达/行为/_sync_party 变更）
    if preserve_narrative:
        for k in ("当前位置", "当前时间", "队伍"):
            if k not in explore and k in existing:
                explore[k] = existing[k]
    path = _explore_path(slot, save_dir)
    _mkdir_slot(slot, save_dir)
    atomic_write_json(path, explore, indent=2)
    return path


def read_history(slot, save_dir=DEFAULT_SAVE_DIR):
    """读取 slot 的过往经历（来自 explore.json），供 GM 回顾剧情、避免臆测。

    返回 {"经历概括": ...}；缺字段以空字符串占位。
    """
    exp = read_explore(slot, save_dir)
    return {
        "经历概括": exp.get("经历概括") or "",
    }


# ----------------------------- 交互轮次与自动存档 -----------------------------
# 交互轮次作为 explore.json 的一个字段持久化：记录世界推进交互轮次（仅返回
# exploration-ui 的 judge 结算成功自增 1；go、返回战斗界面的 judge 不增）。随存档保存、
# 读档恢复到存档时刻值。自动存档判定：当前轮次 % 存档周期 == 0 则触发 save。
# 「距下次自动存档」的剩余轮数由此派生展示。
CHECKPOINT_PERIOD = 5  # 每 5 次世界推进交互（exploration-ui judge 成功回合）触发一次自动存档


def read_round(slot, save_dir=DEFAULT_SAVE_DIR):
    """读取交互轮次（存于 explore.json）；缺失或损坏回退 0。"""
    exp = read_explore(slot, save_dir)
    try:
        return int(exp.get("round", 0))
    except (TypeError, ValueError):
        return 0


def write_round(slot, n, save_dir=DEFAULT_SAVE_DIR):
    """写入总交互轮次到 explore.json（保留其余字段）。"""
    if not _slot_writable(slot):
        return None
    exp = read_explore(slot, save_dir)
    exp["round"] = int(n)
    path = _explore_path(slot, save_dir)
    _mkdir_slot(slot, save_dir)
    atomic_write_json(path, exp, indent=2)
    return path


def rounds_until_save(slot, save_dir=DEFAULT_SAVE_DIR):
    """据当前总交互轮次推算「距下次自动存档」的剩余轮数（界面抬头用）。

    存档判定见 engine：回合开始时 rnd%周期==0 则该回合存档（即第1/6/11...回合）。
    故完成 rnd 个回合后，下一存档回合号 = 满足 k%周期==0 的最小 k≥rnd（rnd 为周期
    倍数时取自身，表示下一回合即存档）对应的回合号 k+1。剩余 = (k+1) - rnd。
    例：rnd=1(刚存)→5；rnd=5(下回合存)→1；rnd=6(刚存)→5。
    """
    rnd = read_round(slot, save_dir)
    p = CHECKPOINT_PERIOD
    k = rnd if rnd % p == 0 else (rnd // p + 1) * p  # 下一存档回合开始时的 rnd
    return (k + 1) - rnd


def checkpoint(slot, state, save_dir=DEFAULT_SAVE_DIR):
    """[遗留 CLI] 每回合自增交互轮次并据 轮次%周期 判定自动存档 + 合并实时状态写入。

    主路径已统一到 engine.py go；保留供 CLI 兼容。逻辑同 settle：
    自增轮次 → 若 轮次%周期==0 则 save（以 state 为叙事，save 内部 auto_diff 人物状态
    并同步 explore.json）；否则合并更新 explore.json 可变字段（保留经历概括）。
    返回 {"saved": bool, "剩余": int}：剩余为本回合界面抬头应显示的「距下次自动存档 N 轮」。
    """
    state = dict(state) if isinstance(state, dict) else {}
    rnd = read_round(slot, save_dir) + 1
    write_round(slot, rnd, save_dir)  # 先落轮次，使存档 payload 捕获到本轮新值
    saved = False
    if rnd % CHECKPOINT_PERIOD == 0:
        save(state, slot, save_dir)  # save 内部 auto_diff 人物状态 + 同步 explore.json
        saved = True
    elif any(k in state for k in EXPLORE_KEYS):
        # 非存档回合：含任一状态字段即合并更新 explore.json（保留经历概括）
        write_explore(slot, state, save_dir, preserve_narrative=True)
    return {"saved": saved, "剩余": rounds_until_save(slot, save_dir)}



def list_slots(save_dir=DEFAULT_SAVE_DIR):
    """列出全部 slot，按最近存档时间降序返回 [meta_dict, ...]（无存档者居末）"""
    if not os.path.isdir(save_dir):
        return []
    slots = []
    for fn in os.listdir(save_dir):
        m = SLOT_RE.match(fn)
        if not (m and os.path.isdir(os.path.join(save_dir, fn))):
            continue
        n = int(m.group(1))
        meta = read_meta(n, save_dir) or {}
        saves = list_saves(n, save_dir)
        slots.append({
            "slot": n,
            "角色名": meta.get("角色名", ""),
            "创建时间": meta.get("创建时间", ""),
            "最近存档": saves[-1][0] if saves else None,
            "存档数": len(saves),
        })
    # 时间戳为 "YYYYMMDD_HHMMSS"，字典序即时间序；按最近存档降序，无存档者（""）沉底
    slots.sort(key=lambda x: x["最近存档"] or "", reverse=True)
    return slots


# --------------------------- .data/ 工作副本 ---------------------------
# 写时复制（copy-on-write）：slot 的 .data/ 只存被改过的条目，其余由 dao 透明回退
# 冻结基线 assets/data/ 读取，故建档/读档无需拷贝全部文件。见 dao._scan_kind 回退逻辑。


def _grant_starter_pack(character):
    """为新建玩家角色发放起始物资：500 铜钱 + 小还丹×2 + 补气丸×2 + 布衣（装备）。

    在 _init_secondary 之前调用：铜钱累加到「铜钱」字段；丹药按数量重复填入「物品」list
    并默认设为战斗携带；布衣穿戴至 装备.护甲（不入物品栏，与武器同例）。
    """
    character["铜钱"] = (character.get("铜钱") or character.get("银两") or 0) + 500
    items = character.setdefault("物品", [])
    items.extend(["小还丹", "小还丹", "补气丸", "补气丸"])
    # 战斗携带消耗品（≤4类）：默认携带小还丹、补气丸
    carry = character.setdefault("携带物品", [])
    for pill in ("小还丹", "补气丸"):
        if pill not in carry:
            carry.append(pill)
    # 起始护甲：布衣直接穿戴
    equip = character.setdefault("装备", {})
    if not equip.get("护甲"):
        equip["护甲"] = "布衣"


def _init_secondary(character):
    """为新建角色派生二级属性并初始化气血/内力为满值。

    一级属性 + 极性 → 二级属性（复刻 dao.derive_secondary，与战斗同源）；
    新建角色无武学、无装备，故无反哺与装备加成，基础派生即为最终值。
    同时写入顶层 气血/气血上限/内力/内力上限（当前 = 上限），供探索模式直接读取。
    一级属性或极性缺失时跳过，保持原角色不变。
    """
    prim = character.get("一级属性")
    pol = character.get("极性")
    if not isinstance(prim, dict) or not isinstance(pol, dict):
        return character
    sec = dq.derive_secondary(prim, pol)
    character["二级属性"] = sec
    character["气血上限"] = sec["气血上限"]
    character["内力上限"] = sec["内力上限"]
    character["气血"] = sec["气血上限"]
    character["内力"] = sec["内力上限"]
    return character


def create_slot(character, save_dir=DEFAULT_SAVE_DIR, data_dir=DEFAULT_DATA_DIR):
    """为新建角色占用一个 slot：写时复制——不拷贝 assets/data/，仅建空 slot 目录并写入玩家角色。

    character: 角色完整 dict（含 名称 等字段）。写入前自动派生二级属性并初始化气血/内力。
    玩家角色存于 .data/characters/<门派>/<角色名>.json；其余条目读取时由 dao 透明回退基线
    assets/data/，故建档无需拷贝全部文件（从 ~24s 降到接近 0）。

    随机抽取落点大区域与起始时辰/时段，初始化 explore.json（建号即写首档，存档由 engine.go 创建角色一并完成），
    随返回值回传 {slot, 当前位置, 当前时间, 剩余}。剩余为「距下次自动存档 N 轮」。
    """
    ensure_dir(save_dir)
    name = character["名称"]
    _init_secondary(character)
    n = next_slot_number(save_dir)
    # 写时复制：仅建空 slot 目录（.data/characters/ 占位），不拷贝基线；
    # 玩家角色直接写入 slot，其余条目经 dao 回退基线读取。
    os.makedirs(os.path.join(slot_data_dir(n, save_dir), "characters"), exist_ok=True)
    dq.set_data_dir(slot_data_dir(n, save_dir))
    dq.write_character(name, character)
    meta = {
        "slot": n,
        "角色名": name,
        "版本": _read_version(),
        "创建时间": _now_timestamp(),
        "最近存档": None,
        "存档数": 0,
    }
    write_meta(n, meta, save_dir)
    region, t = _random_location_time()
    initial_state = {
        "经历概括": f"{name}初入江湖。",
        "任务摘要及进度": [],
        "队伍": [name],
        "当前位置": region,
        "当前时间": t,
        "体力": STAMINA_MAX,
    }
    # 建号时已写首档（engine.go 的 创建角色 一并调 save）——仅初始化 explore.json，使建号返回与 judge 读档可读队伍/位置/时辰
    write_explore(n, initial_state, save_dir, preserve_narrative=False)
    write_round(n, 0, save_dir)  # 交互轮次自建档起计，初值 0
    return {"slot": n, "当前位置": region, "当前时间": t, "剩余": rounds_until_save(n, save_dir)}


def character_derived_view(slot, name, save_dir=DEFAULT_SAVE_DIR):
    """返回与 `query_data(..., derived=True)` 同构的角色派生视图 dict。

    供 create-slot 直接回传玩家初始属性，省去建号后的额外查询。
    输出为角色文件字段（剔除「人设」）+ `_派生(战斗同源)`。
    """
    live = slot_data_dir(slot, save_dir)
    entry = dq.read_character_file(name, data_dir=live)
    if entry is None:
        return None
    out = dict(entry)
    out.pop("人设", None)
    dq.set_data_dir(live)  # 使派生读 .data/ 副本，与 --slot 同源
    out["_派生(战斗同源)"] = dq.derived_overlay(name)
    return out


def write_character(slot, name, character, save_dir=DEFAULT_SAVE_DIR):
    """将角色完整 dict 写入 slot 的 .data/characters/<门派>/<名>.json（GM 修改数据时调用）。

    正式游戏中角色属性的任何变化都应通过此函数（或直接编辑 .data/ 文件）落到 .data/，
    引擎随后读取 .data/ 即可感知；下次 save 时脚本自动 diff 入存档。
    """
    dq.write_character(name, character, data_dir=slot_data_dir(slot, save_dir))


# ----------------------------- 字段级 diff/merge -----------------------------

def _merge_field(base, changes):
    """字段级合并：把 changes 覆盖到 base 上（与读档套用增量一致）。

    - 顶层字段：若 base 与 changes 同字段均为 dict，则做一层深合并
      （子键级覆盖，未出现的子键保留基线值）；否则整体替换。
    - list / 标量：整体替换。
    - base 中不存在的新字段（如 关系度 / 当前位置 等运行时属性）：直接写入。
    """
    if not isinstance(base, dict) or not isinstance(changes, dict):
        return changes
    result = dict(base)
    for k, v in changes.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            merged_sub = dict(result[k])
            merged_sub.update(v)
            result[k] = merged_sub
        else:
            result[k] = v
    return result


def _diff_field(base, live):
    """生成单字段的增量：返回使 _merge_field(base, X) == live 的 X；无变化返回 None。

    - base/live 均为 dict → 一层子键 diff（仅记录变化的子键，对应一层深合并）。
    - 否则（标量/list/类型不同）→ 若不等则整体替换为 live。
    - base 缺失（MISSING 哨兵）→ 整体取 live。
    """
    MISSING = object()
    if base is MISSING:
        return live
    if isinstance(base, dict) and isinstance(live, dict):
        sub = {}
        for sk, sv in live.items():
            bv = base.get(sk, MISSING)
            if bv is MISSING or bv != sv:
                sub[sk] = sv
        return sub or None
    if base != live:
        return live
    return None


def _diff_character(base, live):
    """比对单个角色 live（.data/）与 base（原始 assets/data/），返回字段级增量 dict；无变化返回 {}。"""
    if not isinstance(base, dict):
        base = {}
    if not isinstance(live, dict):
        return {}
    changes = {}
    for k, lv in live.items():
        bv = base.get(k, object())
        d = _diff_field(bv, lv)
        if d is not None:
            changes[k] = d
    return changes


def auto_diff(slot, save_dir=DEFAULT_SAVE_DIR, characters_dir=DEFAULT_CHARACTERS_DIR):
    """扫描 slot 的 .data/characters/，与原始 assets/data/characters 比对，生成人物状态增量。

    返回 {角色名: 字段级增量}，仅含发生变化的角色（与原始 assets/data/ 一致者不入增量）。
    玩家角色（原始 assets/data/ 中不存在）以全量入增量。
    """
    live_data_dir = slot_data_dir(slot, save_dir)
    baseline_data_dir = os.path.dirname(characters_dir)
    delta = {}
    for name in dq.list_names("角色", data_dir=live_data_dir):
        live = dq.read_character_file(name, data_dir=live_data_dir)
        if live is None:
            continue
        # 持久化:False 的临时 NPC 不入存档增量（当前会话可用，读档后不恢复）
        if live.get("持久化") is False:
            continue
        base = dq.read_character_file(name, data_dir=baseline_data_dir) or {}
        diff = _diff_character(base, live)
        if diff:
            delta[name] = diff
    return delta


# ----------------------------- 存档读写 -----------------------------

def list_saves(slot, save_dir=DEFAULT_SAVE_DIR):
    """列出某 slot 内全部存档，按时间戳升序返回 [(timestamp, filepath), ...]"""
    sdir = slot_path(slot, save_dir)
    if not os.path.isdir(sdir):
        return []
    items = []
    for fn in os.listdir(sdir):
        m = FILENAME_RE.match(fn)
        if m:
            base, suf = m.group(1), int(m.group(2) or 0)
            ts = base if suf == 0 else f"{base}_{suf}"
            items.append(((base, suf), ts, os.path.join(sdir, fn)))
    items.sort(key=lambda x: x[0])
    return [(ts, path) for _key, ts, path in items]


def _read_save_label(path):
    """读取列表展示用 label；存档损坏时告警并保留该存档条目。"""
    try:
        payload = read_json(path, expected_type=dict)
    except JsonReadError as exc:
        warn_json_read(exc)
        return ""
    label = payload.get("label")
    return label if isinstance(label, str) else ""


def list_slot_saves(slot, save_dir=DEFAULT_SAVE_DIR):
    """返回单 slot 的存档列表（游戏内读档浏览专用）。结构与 list_all_saves 单项一致：
    {slot, 角色名, 最近存档, 进度, saves}。saves 按时间戳降序（最新在前），每条
    {序号, 时间戳, label}；进度取经历概括（label 全空时）。无存档返回空列表。"""
    m = read_meta(slot, save_dir)
    if not m:
        return []
    saves = []
    for idx, (ts, path) in enumerate(reversed(list_saves(slot, save_dir)), start=1):
        label = _read_save_label(path)
        saves.append({"序号": idx, "时间戳": ts, "label": label})
    progress = ""
    if not any(s["label"] for s in saves):
        progress = read_explore(slot, save_dir).get("经历概括", "") or ""
    return [{
        "slot": slot,
        "角色名": m["角色名"],
        "最近存档": m["最近存档"],
        "进度": progress,
        "saves": saves,
    }]


def list_all_saves(save_dir=DEFAULT_SAVE_DIR):
    """读档界面专用：一次返回全部 slot 及其存档，供 GM 合并渲染读档列表。

    slot 按「最近存档时间戳」降序排列（无存档者居末）；每个 slot 含：
      slot / 角色名 / 最近存档（时间戳，无则 None）/ saves
    saves 为该 slot 全部存档按时间戳**降序**（最新在前），每条：
      {序号, 时间戳, label, 进度}
    进度取存档 label；label 为空时回退该 slot explore.json 的「经历概括」。
    """
    out = []
    for m in list_slots(save_dir):  # 已按最近存档降序
        n = m["slot"]
        saves = []
        for idx, (ts, path) in enumerate(reversed(list_saves(n, save_dir)), start=1):
            label = _read_save_label(path)
            saves.append({"序号": idx, "时间戳": ts, "label": label})
        progress = ""
        if not any(s["label"] for s in saves):
            progress = read_explore(n, save_dir).get("经历概括", "") or ""
        out.append({
            "slot": n,
            "角色名": m["角色名"],
            "最近存档": m["最近存档"],
            "进度": progress,
            "saves": saves,
        })
    return out


def prune(slot, save_dir=DEFAULT_SAVE_DIR, keep=MAX_SAVES_PER_SLOT):
    """保留该 slot 最新的 keep 个存档，删除多余的（时间戳最早者优先删除）"""
    items = list_saves(slot, save_dir)
    deleted = []
    if len(items) > keep:
        surplus = items[: len(items) - keep]
        for _ts, path in surplus:
            try:
                os.remove(path)
                deleted.append(path)
            except OSError:
                pass
    return deleted


def delete_save(slot, target, save_dir=DEFAULT_SAVE_DIR):
    """删 slot 内单个存档点（target 同 restore 解析：File_N/时间戳/label/子串）。
    删后更新 meta 的存档数/最近存档。返回剩余存档数。"""
    path = _resolve_save_path(target, slot, save_dir)
    os.remove(path)
    items = list_saves(slot, save_dir)
    meta = read_meta(slot, save_dir) or {"slot": int(slot), "角色名": ""}
    meta["最近存档"] = items[-1][0] if items else None
    meta["存档数"] = len(items)
    write_meta(slot, meta, save_dir)
    return len(items)


def delete_slot(slot, save_dir=DEFAULT_SAVE_DIR):
    """删整个 slot 目录（角色 + 全部存档点 + explore.json/meta）。不可恢复。"""
    sp = slot_path(slot, save_dir)
    if os.path.exists(sp):
        shutil.rmtree(sp)


def save(state, slot, save_dir=DEFAULT_SAVE_DIR, label=None, keep=MAX_SAVES_PER_SLOT,
         characters_dir=DEFAULT_CHARACTERS_DIR):
    """写入一份存档到指定 slot。返回写入的文件路径。

    state: 叙事状态 dict（经历概括 / 任务摘要及进度 等）；其中 `人物状态`
        由脚本自动 diff `.data/` 生成，无需 GM 提供（若提供也会被覆盖）。
    label: 可选备注，仅写入文件内容，不影响文件名。
    """
    if not _slot_writable(slot):
        raise ValueError(f"非法槽位 slot={slot}：slot<=0 为未选存档哨兵，禁止写入存档")
    sdir = slot_path(slot, save_dir)
    os.makedirs(sdir, exist_ok=True)
    ts = _now_timestamp()
    path = os.path.join(sdir, f"savefile_{ts}.json")
    n = 1
    while os.path.exists(path):
        path = os.path.join(sdir, f"savefile_{ts}_{n}.json")
        n += 1
    state = dict(state) if isinstance(state, dict) else {}
    state["人物状态"] = auto_diff(slot, save_dir, characters_dir)
    payload = {"version": _read_version(), "timestamp": ts, "label": label,
               "round": read_round(slot, save_dir), "state": state,
               MERCHANT_KEY: read_merchant_cache(slot, save_dir),
               MAP_OVERLAY_KEY: read_map_overlay(slot, save_dir),
               SCENE_TYPES_OVERLAY_KEY: read_scene_types_overlay(slot, save_dir)}
    atomic_write_json(path, payload, indent=2)
    # 同步 explore.json：把存档定稿的过往经历/任务信息等写回实时镜像
    write_explore(slot, state, save_dir, preserve_narrative=False)
    prune(slot, save_dir, keep)
    items = list_saves(slot, save_dir)
    meta = read_meta(slot, save_dir) or {"slot": int(slot), "角色名": ""}
    meta["最近存档"] = items[-1][0] if items else ts
    meta["存档数"] = len(items)
    write_meta(slot, meta, save_dir)
    return path


def restore(slot, target, save_dir=DEFAULT_SAVE_DIR, data_dir=DEFAULT_DATA_DIR):
    """读档：写时复制——清空 slot 的 .data/（仅删 slot 写过的角色，不重拷基线），
    再把存档的人物状态增量相对冻结基线合并后写入 slot。

    增量相对原始 assets/data/（冻结基线）：对每角色读基线为 base，套用增量得到该存档时刻
    的完整状态，写入 slot；slot 无文件的条目读取时由 dao 透明回退基线。
    返回存档的完整 state（叙事 + 人物状态增量），供 GM 恢复场景叙事之用。
    脚本完成全部合并，GM 无需手动合并。
    """
    if not _slot_writable(slot):
        raise ValueError(f"非法槽位 slot={slot}：slot<=0 为未选存档哨兵，禁止读档")
    # 先完整读取并校验快照及其附属状态，再开始删除或覆盖当前 slot。
    path = _resolve_save_path(target, slot, save_dir)
    payload = _read_save_payload(path)
    state = _save_state_from_payload(payload, path)
    delta = state.get("人物状态")
    saved_round = _load_round(path, slot, save_dir, payload)
    saved_merchant = _load_merchant_cache(path, slot, save_dir, payload)
    saved_map = _load_map_overlay(path, slot, save_dir, payload)
    saved_scene_types = _load_scene_types_overlay(path, slot, save_dir, payload)
    live_data_dir = slot_data_dir(slot, save_dir)
    # 清空 slot 写时复制副本（删 slot 的 .data/，重建空 characters/），不触碰冻结基线
    if os.path.exists(live_data_dir):
        shutil.rmtree(live_data_dir)
    os.makedirs(os.path.join(live_data_dir, "characters"), exist_ok=True)
    dq.set_data_dir(live_data_dir)  # 重定向到 slot 并清读缓存
    baseline_dir = data_dir if data_dir is not None else DEFAULT_DATA_DIR
    if isinstance(delta, dict) and delta:
        for name, changes in delta.items():
            base = dq.read_character_file(name, data_dir=baseline_dir) or {}
            merged = _merge_field(base, changes)
            # 写入域(slot .data)刚被 rmtree，三态：
            # ① 写入域已有该角色（如重新读档时先写成的旧档）→ update_char 覆盖更新
            # ② 写入域无、基线也无（纯玩家自创新角色）→ write_character 新建
            # ③ 写入域无、基线有（基线 NPC 改版快照）→ write_character 会撞 "全局唯一名"
            #    校验，改走底层 _store 覆盖写（写入域内同名由 _store 自身去重）
            if dq.read_character_file(name, data_dir=live_data_dir) is not None:
                dq.update_char(name, merged, data_dir=live_data_dir)
            else:
                try:
                    dq.write_character(name, merged, data_dir=live_data_dir)
                except ValueError:
                    dq._store("角色", dq._normalize_character(merged), data_dir=live_data_dir)
    # 镜像同步：把存档的 GM 维护字段（含过往经历/任务信息）写回 explore.json，
    # 使读档后实时状态跟上存档点（修正旧区域名为 map.json 节点名）
    if isinstance(state, dict) and state.get("当前位置"):
        state["当前位置"] = _fix_region(state["当前位置"])
    write_explore(slot, state, save_dir, preserve_narrative=False)
    # 交互轮次随存档保存，读档恢复到存档时刻的轮次
    write_round(slot, saved_round, save_dir)
    # 商人货架、场景图与场景类型均使用写入前已校验的快照值。
    write_merchant_cache(slot, saved_merchant, save_dir)
    write_map_overlay(slot, saved_map, save_dir)
    write_scene_types_overlay(slot, saved_scene_types, save_dir)
    # 返回值带「剩余」，供 GM 直接填界面抬头「距下次自动存档 N 轮」，读档后无需另查
    state["剩余"] = rounds_until_save(slot, save_dir)
    return state


def _resolve_save_path(target, slot, save_dir=DEFAULT_SAVE_DIR):
    """定位存档文件路径：完整文件名/时间戳/路径/任意可匹配子串/label/序号（slot 目录内解析）。

    序号写法 file_n / File_n（大小写不敏感，n≥1）：按时间戳从新到旧排序的第 n 个存档。
    """
    sdir = slot_path(slot, save_dir)
    # 序号定位：file_n / File_n（时间戳降序，1 基索引）
    m_idx = re.fullmatch(r"(?i)file_(\d+)", target.strip())
    if m_idx:
        idx = int(m_idx.group(1))
        items = list(reversed(list_saves(slot, save_dir)))  # 最新在前
        if 1 <= idx <= len(items):
            return items[idx - 1][1]
        raise FileNotFoundError(f"在 slot {slot} 中找不到存档: {target}（共 {len(items)} 个）")
    if os.path.isfile(target):
        return target
    cand = target if target.endswith(".json") else f"savefile_{target}.json"
    path = cand if os.path.isabs(cand) else os.path.join(sdir, cand)
    if os.path.isfile(path):
        return path
    for _ts, p in reversed(list_saves(slot, save_dir)):
        if target in os.path.basename(p) or target in _ts:
            return p
    for _ts, p in reversed(list_saves(slot, save_dir)):
        label = _read_save_label(p)
        if label and target in label:
            return p
    raise FileNotFoundError(f"在 slot {slot} 中找不到存档: {target}")


def _load_round(target, slot, save_dir=DEFAULT_SAVE_DIR, payload=None):
    """读取存档顶层「交互轮次」；字段缺失（旧存档）回退当前 explore.json 轮次。"""
    path = _resolve_save_path(target, slot, save_dir)
    payload = _read_save_payload(path) if payload is None else payload
    if "round" not in payload:
        return read_round(slot, save_dir)
    try:
        return int(payload["round"])
    except (TypeError, ValueError) as exc:
        raise JsonSchemaError(path, "round 须为整数") from exc


def _fix_state(state):
    """读档后统一修复旧存档 state：补全新字段、清除已废字段。原地修改并返回。

    - 无 `当前时间`（旧版用字符 `当前时段`/`当前时辰`）→ 据旧 `当前时辰` 推算该时辰初刻，
      无旧时辰则补 0（第一天起始）
    - 无 `体力` → 补满（STAMINA_MAX）
    - 清除已废的 `当前时段`/`当前时辰`
    """
    if not isinstance(state, dict):
        return state
    if "当前时间" not in state:
        hour = state.get("当前时辰")
        idx = ut._ZHI.index(hour) if isinstance(hour, str) and hour in ut._ZHI else 0
        state["当前时间"] = idx * ut.UNITS_PER_ZHI  # 时辰初刻
    if "体力" not in state:
        state["体力"] = STAMINA_MAX
    for k in ("当前时段", "当前时辰"):
        state.pop(k, None)
    return state


def _read_save_payload(path):
    """严格读取存档顶层对象。"""
    return read_json(path, expected_type=dict)


def _save_state_from_payload(payload, path):
    """校验并迁移存档 state。"""
    state = payload.get("state")
    if not isinstance(state, dict):
        raise JsonSchemaError(path, "state 须为对象")
    return _fix_state(state)


def _read_save_state(path):
    """读取并校验存档 payload，返回兼容迁移后的 state。"""
    return _save_state_from_payload(_read_save_payload(path), path)


def load(target, slot, save_dir=DEFAULT_SAVE_DIR):
    """读取指定 slot 内的存档，返回原始 state dict（叙事 + 人物状态增量，未合并）。

    target 可为：完整文件名 / 时间戳 / 文件路径 / 任意可匹配子串（均在 slot 目录内解析）。
    """
    return _read_save_state(_resolve_save_path(target, slot, save_dir))


def latest(slot, save_dir=DEFAULT_SAVE_DIR):
    """返回指定 slot 内最新存档的原始 state，无存档时返回 None。"""
    items = list_saves(slot, save_dir)
    if not items:
        return None
    return _read_save_state(items[-1][1])


def _load_char_file(char_dir, name):
    """从 .data/characters/ 读角色 JSON 为全新 dict（不触碰缓存）；缺失返回 None。

    char_dir 形如 <data_root>/characters；经 dao 按 data_root 读取。
    """
    return dq.read_character_file(name, data_dir=os.path.dirname(char_dir))


def _party_row(entry):
    """从人物状态条目抽取状态行四要素（名称/气血/气血上限/内力/内力上限）。"""
    row = {"名称": entry.get("名称")}
    for k in ("气血", "气血上限", "内力", "内力上限"):
        if k in entry:
            row[k] = entry[k]
    return row


def summarize_state(state, slot, save_dir=DEFAULT_SAVE_DIR):
    """把 restore 后的完整 state 压缩为 GM 恢复叙事所需的精简视图（仅裁剪对外输出）。

    存档原始内容与 restore() 返回值不变。本函数额外对人物状态中的角色完成完整派生
    （经 dao.derive_character，与 query_data(..., derived=True) 同源：基础派生 + 武学反哺
    + 装备加成），使状态行所需的气血/内力及其上限一次取齐——GM 读档后无需再查派生。
    - 顶层保留场景与叙事字段：当前位置 / 当前时间 / 经历概括 / 任务摘要。
    - 人物状态：每角色派生后取 气血/气血上限/内力/内力上限/在队/当前位置/经验值/铜钱（缺失回退增量；旧档「银两」兼容）。
      玩家定义性字段（一级属性/武艺/技艺/武学/装备/物品 等）不重复输出——已写入 .data/，需时 dao 取。
    - 在队状态：玩家 + 在队队友的精简状态行视图（名称/气血/气血上限/内力/内力上限），玩家居首。
    """
    summary = {}
    for key in ("当前位置", "当前时间",
                "经历概括", "任务摘要", "任务摘要及进度", "状态提示", "剩余"):
        if key in state:
            summary[key] = state[key]
    # 附带换算后的时间字符串/时段（与 create-slot、engine.py go 对齐）
    cur_time = state.get("当前时间")
    if cur_time is not None:
        summary["时间"] = time_to_str(cur_time)
        summary["时段"] = time_slot_of(cur_time)
    delta = state.get("人物状态") or {}
    char_dir = os.path.join(slot_data_dir(slot, save_dir), "characters")
    # 重定向数据目录到 .data/，使 load_skills/load_characters 读到正确副本；角色 dict 自行从文件读全新对象
    dq.set_data_dir(slot_data_dir(slot, save_dir))
    skills_db = dq.load_skills()
    characters_db = dq.load_characters()
    fields = ("气血", "气血上限", "内力", "内力上限", "在队", "当前位置", "经验值", "铜钱")
    chars = {}
    for name in delta:
        live = _load_char_file(char_dir, name)
        if live is None:
            live = dict(delta.get(name) or {})
        try:
            derived = dq.derive_character(live, characters_db, skills_db)
        except (KeyError, TypeError):
            derived = live  # 缺一级属性/极性等无法派生时回退原始（上限可能缺失）
        changes = delta.get(name) or {}
        entry = {"名称": name}
        for k in fields:
            if k in derived:
                entry[k] = derived[k]
            elif k in changes:
                entry[k] = changes[k]
        # 铜钱兼容旧档「银两」字段
        if "铜钱" not in entry:
            if "银两" in derived:
                entry["铜钱"] = derived["银两"]
            elif "银两" in changes:
                entry["铜钱"] = changes["银两"]
        chars[name] = entry
    summary["人物状态"] = chars
    # 在队状态：玩家居首 + 在队队友，状态行就绪
    meta = read_meta(slot, save_dir) or {}
    player_name = meta.get("角色名")
    # 在队名单优先取顶层 队伍 数组；缺省回退到人物状态的 在队 字段
    party_names = state.get("队伍")
    party = []
    if player_name and player_name in chars:
        party.append(_party_row(chars[player_name]))
    if isinstance(party_names, list):
        for name in party_names:
            if name != player_name and name in chars:
                party.append(_party_row(chars[name]))
    else:
        for name, entry in chars.items():
            if name == player_name:
                continue
            if entry.get("在队"):
                party.append(_party_row(entry))
    if party:
        summary["在队状态"] = party
    return summary


# ----------------------------- 命令行入口 -----------------------------

def _cli(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]

    if cmd == "create-slot":
        raw = sys.stdin.read()
        try:
            character = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"create-slot: 角色 JSON 解析失败（{e}）——需从 stdin 传入角色完整 JSON", file=sys.stderr)
            return 2
        if not isinstance(character, dict) or not character.get("名称"):
            print("create-slot: 角色 JSON 缺少「名称」字段", file=sys.stderr)
            return 2
        info = create_slot(character)
        n = info["slot"]
        view = character_derived_view(n, character["名称"])
        out = {"ok": True, "slot": n, "角色名": character.get("名称"),
               "落点": info["当前位置"], "当前时间": info["当前时间"],
               "时间": time_to_str(info["当前时间"]), "时段": time_slot_of(info["当前时间"]),
               "剩余": info["剩余"], "角色": view}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if cmd == "write-char":
        # 用法: write-char <slot> <角色名>；角色完整 JSON 从 stdin 读取
        if len(argv) < 3:
            print("用法: write-char <slot> <角色名>", file=sys.stderr)
            return 2
        character = json.loads(sys.stdin.read())
        write_character(argv[1], argv[2], character)
        print(json.dumps({"ok": True, "slot": int(argv[1]), "角色名": argv[2]}, ensure_ascii=False))
        return 0

    if cmd == "save":
        # 用法: save <slot> [label]；叙事 state 从 stdin 读取（JSON）
        if len(argv) < 2:
            print("用法: save <slot> [label]", file=sys.stderr)
            return 2
        slot = argv[1]
        label = argv[2] if len(argv) > 2 else None
        state = json.loads(sys.stdin.read())
        path = save(state, slot, label=label)
        print(json.dumps({"ok": True, "slot": int(slot), "path": path, "label": label}, ensure_ascii=False))
        return 0

    if cmd == "write-explore":
        # 用法: write-explore <slot>；GM 维护字段从 stdin 读取（JSON），写入 explore.json
        if len(argv) < 2:
            print("用法: write-explore <slot>", file=sys.stderr)
            return 2
        data = json.loads(sys.stdin.read())
        path = write_explore(argv[1], data)
        print(json.dumps({"ok": True, "slot": int(argv[1]), "path": path}, ensure_ascii=False))
        return 0

    if cmd == "read-explore":
        # 用法: read-explore <slot>；输出 explore.json 全量（GM 维护字段）
        if len(argv) < 2:
            print("用法: read-explore <slot>", file=sys.stderr)
            return 2
        print(json.dumps(read_explore(argv[1]), ensure_ascii=False, indent=2))
        return 0

    if cmd == "read-tasks":
        # 用法: read-tasks <slot>；输出任务摘要及进度（来自 explore.json）
        if len(argv) < 2:
            print("用法: read-tasks <slot>", file=sys.stderr)
            return 2
        print(json.dumps(read_tasks(argv[1]), ensure_ascii=False, indent=2))
        return 0

    if cmd == "read-history":
        # 用法: read-history <slot>；输出过往经历（来自 explore.json），供 GM 回顾剧情
        if len(argv) < 2:
            print("用法: read-history <slot>", file=sys.stderr)
            return 2
        print(json.dumps(read_history(argv[1]), ensure_ascii=False, indent=2))
        return 0

    if cmd == "checkpoint":
        # 用法: checkpoint <slot>；每回合开始调用，stdin 传当前叙事状态 JSON，
        # 据持久化计数器自动判定存档（归零则直接 save）或仅更新计数，返回 saved/剩余
        if len(argv) < 2:
            print("用法: checkpoint <slot>", file=sys.stderr)
            return 2
        try:
            state = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(f"checkpoint: 叙事状态 JSON 解析失败（{e}）", file=sys.stderr)
            return 2
        result = checkpoint(argv[1], state)
        print(json.dumps(result, ensure_ascii=False))
        return 0

    if cmd == "restore":
        # 用法: restore <slot> <目标>：脚本重建 .data/ 并套用增量，输出精简 state 供 GM 恢复叙事
        if len(argv) < 3:
            print("用法: restore <slot> <文件名|时间戳|路径|子串>", file=sys.stderr)
            return 2
        slot = argv[1]
        state = restore(slot, argv[2])
        print(json.dumps(summarize_state(state, slot), ensure_ascii=False, indent=2))
        return 0

    if cmd == "load":
        if len(argv) < 3:
            print("用法: load <slot> <文件名|时间戳|路径|子串>", file=sys.stderr)
            return 2
        state = load(argv[2], argv[1])
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    if cmd == "list-slots":
        slots = list_slots()
        if not slots:
            print("（暂无 slot）")
        for m in slots:
            print(f"slot_{m['slot']}  {m['角色名']}  存档{m['存档数']}  最近{m['最近存档']}")
        return 0

    if cmd == "list-saves":
        if len(argv) < 2:
            print("用法: list-saves <slot>", file=sys.stderr)
            return 2
        items = list_saves(argv[1])
        if not items:
            print("（该 slot 暂无存档）")
        for ts, path in reversed(items):  # 降序：最近存档在前
            label = _read_save_label(path)
            print(f"{ts}  {os.path.basename(path)}  {label}")
        return 0

    if cmd == "list-all-saves":
        # 读档界面专用：一次列出全部 slot 及其存档（slot 按最新存档时间戳降序）。
        # 输出界面友好格式，GM 直接拼为读档列表渲染。
        all_saves = list_all_saves()
        if not all_saves:
            print("尚无存档可续")
            return 0
        for s in all_saves:
            print(f"【Slot_{s['slot']} {s['角色名']}】")
            if not s["saves"]:
                print("（无存档）")
                continue
            for sv in s["saves"]:
                ts = sv["时间戳"]
                pretty = f"{ts[0:4]}/{ts[4:6]}/{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
                desc = sv["label"] or s["进度"] or ""
                print(f"- File_{sv['序号']} {pretty} — {desc}")
        return 0

    if cmd == "latest":
        if len(argv) < 2:
            print("用法: latest <slot>", file=sys.stderr)
            return 2
        state = latest(argv[1])
        if state is None:
            print("（该 slot 暂无存档）", file=sys.stderr)
            return 1
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    if cmd == "prune":
        if len(argv) < 2:
            print("用法: prune <slot>", file=sys.stderr)
            return 2
        deleted = prune(argv[1])
        print(json.dumps({"ok": True, "slot": int(argv[1]), "deleted": deleted}, ensure_ascii=False))
        return 0

    print(f"未知命令: {cmd}\n可用: create-slot | write-char | save | checkpoint | restore | load | write-explore | read-explore | read-tasks | read-history | list-slots | list-saves | list-all-saves | latest | prune", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
