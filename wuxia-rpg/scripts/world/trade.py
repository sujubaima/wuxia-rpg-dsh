#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易辅助脚本 —— 辅助大世界交易系统。

当前接口：取卖家的可售物品列表。

用法：
  python3 scripts/trade.py 可售物品 <卖家> [--商人] [--种类 <标签>...] [--slot <N>]

参数：
  <卖家>           卖家名称（落盘 NPC 或临时 NPC）
  --商人           本次交易以商人身份进行（缺省=非商人，即玩家向普通 NPC 买卖）
  --种类 <标签>    售卖物品的种类，可多次指定（多标签任一命中即符合）。一级标签
                   （武器/护甲/冠巾/饰品/消耗品/秘籍/材料/其他）或二级标签
                   （刀/剑/丹药/技艺书/…）皆可；省略则不限种类
  --slot <N>       存档槽号（正式游戏读 slot 的 .data/，调试读 assets/data/）

返回：JSON 数组，每项为可售物品的概要：
  {名称, 类型, 子类型, 品级, 价格, 描述}
  落盘 NPC 物品栏物品另含 数量。

规则：
  · 卖家可落盘读到（dao.get("角色", 卖家) 非空）且非商人交易 → 返回其物品栏中
    符合种类标签的物品（聚合计数，不限数量）。
  · 卖家不可落盘读且非商人交易（临时 NPC）→ 按种类从物品库随机筛选最多 4 类。
  · 商人交易 → 按种类从物品库随机筛选最多 12 类。
  · 多个 --种类 标签为「或」关系，命中任一即符合。
"""

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from common import dao as dq

# 物品概要字段（与 dao.inventory 风格一致）
_ITEM_FIELDS = ("类型", "子类型", "品级", "价格", "描述")

# 落盘 NPC 物品栏：最多返回的物品种类数上限（避免一次倾泻过多）
_PERSIST_INV_CAP = 20
# 临时 NPC 非商人：随机物品种类数上限
_TEMP_NPC_CAP = 4
# 商人交易：随机物品种类数上限
_MERCHANT_CAP = 12

# 品级出现率（仅作用于从物品库随机筛选的分支；落盘 NPC 物品栏不受此限）
# 0品 100% / 1品 56.25% / 2品 6.25% / 3品 1%
_TIER_APPEAR_RATE = {0: 1.0, 1: 0.5625, 2: 0.0625, 3: 0.01}


def _tier_quotas(cap):
    """把总槽位 cap 按品级出现率比例切分为各品级配额（最大余数法，总和恰为 cap）。

    每个品级先取比例的整数下取整，剩余槽位按小数余数从大到小逐一补齐，保证总和恰为 cap。
    小配额品级按比例归零（如 cap=10 时 3品≈0.06→0、2品≈0.38→0），不保底。
    返回 {品级: 配额}，仅含出现率>0 的品级。
    """
    rates = {g: r for g, r in _TIER_APPEAR_RATE.items() if r > 0}
    total_rate = sum(rates.values())
    if total_rate <= 0 or cap <= 0:
        return {g: 0 for g in rates}
    quot = {g: cap * r / total_rate for g, r in rates.items()}
    quota = {g: int(q) for g, q in quot.items()}  # 下取整
    remain = cap - sum(quota.values())
    # 按小数余数从大到小补齐（余数相同按品级从高到低，稳定可复现）
    order = sorted(rates.keys(),
                   key=lambda g: (quot[g] % 1.0, -g), reverse=True)
    i = 0
    while remain > 0 and order:
        g = order[i % len(order)]
        quota[g] += 1
        remain -= 1
        i += 1
    return quota


def _is_sellable(rec):
    """物品是否可进入随机售卖池：3 品武器一律不可售卖，其余按品级出现率参与。"""
    if rec.get("类型") == "武器" and rec.get("品级") == 3:
        return False
    return True


def _item_summary(rec, with_count=1):
    """物品条目 → 概要 dict。rec 为物品库记录；默认附「数量: 1」（物品库单件）。"""
    entry = {"名称": rec['名称'], "数量": with_count}
    for k in _ITEM_FIELDS:
        if k in rec:
            entry[k] = rec[k]
    return entry


def _matches_any_tag(rec, tags):
    """物品记录是否命中给定种类标签集合中的任一标签（一级 类型 或二级 子类型 任一匹配）。

    tags 为空（None 或空集合）则视为不限种类，恒为 True。
    """
    if not tags:
        return True
    t = rec.get("类型")
    s = rec.get("子类型")
    s_is_manual = isinstance(s, str) and s.endswith("秘籍")
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        if t == tag or s == tag:
            return True
        # 兼容「秘籍」习惯说法：各「<武学类型>秘籍」子类型统一归「秘籍」
        if tag == "秘籍" and s_is_manual:
            return True
    return False


def _persisted_inventory_items(seller, tags, cap=_PERSIST_INV_CAP):
    """落盘 NPC 物品栏 → 符合种类标签的物品列表（聚合计数）。"""
    inv = dq.inventory(seller)  # [{名称, 数量, 类型, 子类型, 品级, 描述, ...}]
    if inv is None:
        return None  # 非落盘
    picked = []
    for it in inv:
        nm = it.get("名称", "").strip("`")
        count = it.get("数量", 1)
        if not _matches_any_tag(it, tags):
            continue
        entry = {"名称": it.get("名称", nm), "数量": count}
        for k in _ITEM_FIELDS:
            if k in it:
                entry[k] = it[k]
        picked.append(entry)
        if len(picked) >= cap:
            break
    return picked


def _stock_count(rec):
    """商人货架单件备货量：按品级——低品消耗品备货多，高品珍物仅 1 件。"""
    tier = rec.get("品级", 0)
    if tier is None:
        tier = 0
    if tier >= 3:
        return 1
    if tier == 2:
        return random.randint(1, 3)
    if tier == 1:
        return random.randint(2, 5)
    return random.randint(3, 8)  # 0品/凡品


def _random_pool_items(tags, cap):
    """从物品库按种类标签筛选，按品级出现率比例分配槽位，最多 cap 类。

    · 3 品武器不可售卖，直接排除。
    · 总槽位 cap 按品级出现率比例切分为各品级配额（如商人 cap=12：0品8 / 1品4 / 2品0 / 3品0），
      每品级在其候选中随机取不超过配额数，品级从高到低排列。
    · 出现率体现为各品级的槽位占比；池不足时该品级按实际候选数上架，总数可能不足 cap。
    · 商人货架每件备货量按品级随机（见 _stock_count）；临时 NPC 每件 1 件。
    """
    pool = dq.load_all("物品")  # {名称: rec}
    by_tier = {}
    for rec in pool.values():
        if not _matches_any_tag(rec, tags) or not _is_sellable(rec):
            continue
        by_tier.setdefault(rec.get("品级", 0), []).append(rec)
    if not by_tier:
        return []
    quotas = _tier_quotas(cap)
    result = []
    # 品级从高到低填充
    for tier in sorted(by_tier.keys(), reverse=True):
        q = quotas.get(tier, 0)
        if q <= 0:
            continue
        cands = by_tier[tier]
        k = min(q, len(cands))
        chosen = random.sample(cands, k)
        result.extend(_item_summary(rec, _stock_count(rec)) for rec in chosen)
    return result


def seller_offer(seller, merchant=False, tags=None):
    """取卖家的可售物品列表。

    tags 为种类标签集合（一级 类型 或二级 子类型 任一命中即符合），空则不限种类。

  . 卖家落盘且非商人 → 其物品栏中符合种类的物品（聚合计数）。
  . 卖家临时（不可落盘）且非商人 → 物品库随机 ≤4 类。
  . 商人交易 → 物品库随机 ≤12 类。
    返回 JSON 可序列化的 list（非 None；卖家不可落盘即视作临时 NPC）。
    """
    # 规整 tags：None / 单字符串 → 集合
    if tags is None:
        tags = set()
    elif isinstance(tags, str):
        tags = {tags}
    else:
        tags = set(tags)
    tags.discard(None)

    # 判定是否落盘：能读到角色记录即落盘 NPC
    persisted = dq.get("角色", seller) is not None

    if merchant:
        return _random_pool_items(tags, _MERCHANT_CAP)

    if persisted:
        items = _persisted_inventory_items(seller, tags)
        return items if items is not None else []
    # 临时 NPC
    return _random_pool_items(tags, _TEMP_NPC_CAP)


# ----------------------------- CLI -----------------------------

def _parse_args(argv):
    positionals = []
    merchant = False
    tags = []
    slot = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--商人":
            merchant = True; i += 1; continue
        if a == "--种类" and i + 1 < len(argv):
            tags.append(argv[i + 1]); i += 2; continue
        if a == "--slot" and i + 1 < len(argv):
            slot = argv[i + 1]; i += 2; continue
        positionals.append(a); i += 1
    return positionals, merchant, tags, slot


def main():
    positionals, merchant, tags, slot = _parse_args(sys.argv[1:])
    if not positionals:
        print(__doc__, file=sys.stderr)
        return 2
    cmd = positionals[0]
    if cmd in ("可售物品", "offer", "shop"):
        if len(positionals) < 2:
            print("用法：trade 可售物品 <卖家> [--商人] [--种类 <标签>...] [--slot <N>]",
                  file=sys.stderr)
            return 2
        seller = positionals[1]
        if slot is not None:
            dq.set_slot(slot)
        result = seller_offer(seller, merchant=merchant, tags=tags)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"未知指令：{cmd}\n可用：可售物品 / offer / shop", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
