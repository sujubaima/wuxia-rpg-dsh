---
name: wuxia-rpg-dao-query
description: 数据、设定、武学推荐、地图与大世界判定接口速查
---

# 查询与判定速查

正式游戏传当前 `槽位`；未建档时传 `0`读取基线。GM 禁止直接读取或修改数据 JSON。

## 基础查询

优先调用 `wuxia_query`；不可用时：

```bash
echo '{"槽位":N,"类型":"角色","名称":["柳序"],"派生":true,"字段":["一级属性","技艺"]}' | python3 scripts/engine.py query
```

参数：
- `类型`：角色、武学、物品、状态、阵营。
- `名称`：字符串数组；不传则列出该类型全部名称，多名称一次批量查询。
- `派生`：角色查询附带战斗同源派生属性。
- `字段`：仅返回指定字段。
- `等级`：武学查询返回该精进等级的特效说明，缺省1。

人物人设与所属门派须用设定查询。

## 设定查询

优先调用 `wuxia_setting`（`槽位`、`目标`）；不可用时：

```bash
echo '{"槽位":N,"目标":"门派或人物"}' | python3 scripts/engine.py setting
```

- 门派：返回描述、地理位置、武学及成员人设/生死。
- 人物：返回阵营、人设、生死、预设标记及所属门派。
- 安排人物登场前先核实；`死亡=true`者不得正面登场。

## 武学推荐

优先调用 `wuxia_recommend`；不可用时：

```bash
echo '{"槽位":N,"姓名":"…","阵营":"江湖","一级属性":{"内功":N,"力道":N,"身法":N,"根骨":N},"武学偏好":"剑法"}' | python3 scripts/engine.py recommend
```

`武学偏好`取剑法、刀法、长兵、奇门、暗器、搏击。返回心法、主动武学、装备简表，每类最多6项；自创角色优先从推荐结果配置。

## 地图查询

优先调用 `wuxia_map_query`（`槽位`、`区域`）；不可用时：

```bash
echo '{"槽位":N,"区域":"苏州"}' | python3 scripts/engine.py map-query
echo '{"槽位":N,"区域":"配额"}' | python3 scripts/engine.py map-query
```

区域查询返回基线/新增场景、类型、功能NPC、方位出口、孤点与配额余量；支持唯一子串匹配。设计移动、登记或连通场景前，对现状不确定时先查。

## 大世界判定

判定优先调 `wuxia_check`，随机事件优先调 `wuxia_random_event`；不可用时：

```bash
echo '{"槽位":N,"属性":["身法"],"判定角色":["柳序"],"对抗":"@30","基础成功率":50}' | python3 scripts/engine.py check
echo '{"槽位":N,"基础成功率":15}' | python3 scripts/engine.py random-event
```

- `属性`、`判定角色`可传多个，取均值；NPC 不得作为判定方。
- `对抗`传角色名（可逗号多个）或 `@数值`。
- `基础成功率`通常易70、普通50、困难30、极难15。
- 判定返回 `结果`与`提示`；数字不向玩家展示。

完整判定原则见 [wuxia-rpg-exploration-rules.md](./wuxia-rpg-exploration-rules.md)「判定系统」，字段定义见 [wuxia-rpg-data-schema.md](./wuxia-rpg-data-schema.md)。
