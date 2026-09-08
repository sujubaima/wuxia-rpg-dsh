# 核心引擎

`scripts/` 是武侠 RPG 的确定性规则与状态引擎。它接收结构化 JSON，完成数据查询、行为结算、判定、战斗推进和存档读写，再返回结构化 JSON 供 GM、Web 或 DSH 前端使用。

引擎负责：

- 校验行为与状态变化；
- 计算资源、时间、属性、战斗和随机结果；
- 维护角色、世界、战斗与存档状态；
- 组装界面所需的结构化数据。

引擎不负责：

- 理解玩家的自然语言；
- 决定剧情如何发展；
- 替 GM 撰写叙事；
- 直接渲染 Markdown 或浏览器界面。

## 1. 运行要求

- Python 3.9 或更高版本；
- 仅使用 Python 标准库，无需安装 pip 依赖；
- 默认存档目录为 `~/.wuxia/save/`；
- 可通过 `WUXIA_RPG_SAVE_DIR` 指定其他存档目录。

建议从 `wuxia-rpg/` 目录运行命令：

```bash
python3 scripts/engine.py
```

不带子命令时会打印 CLI 概览。

## 2. 统一 CLI 协议

主入口是 `engine.py`：

```bash
python3 scripts/engine.py <command>
```

每次调用从 stdin 读取一个 JSON 值，并向 stdout 输出 JSON。JSON 解析失败或参数不合法时，CLI 通常以状态码 `2` 退出；部分用法错误会写入 stderr。

### 命令一览

| 命令 | 定位 | 主要输入 |
|---|---|---|
| `go` | 结算玩家主动行为 | `槽位`、`行为` |
| `judge` | 写入 GM 推演后的剧情与状态变化 | `槽位`、`行为`、`当前剧情`、`场景要素`、`经历概括` |
| `check` | 执行属性或技艺判定 | `槽位`、`属性`、`判定角色`、`对抗`、`基础成功率` |
| `random-event` | 判断随机事件是否触发 | `槽位`、`基础成功率` |
| `query` | 查询角色、武学、物品、状态、阵营或场景角色 | `槽位`、`类型`，以及可选查询条件 |
| `setting` | 聚合查询人物或门派设定 | `槽位`、`目标` |
| `recommend` | 推荐武学、心法和装备 | `槽位`、`一级属性`、`武学偏好`等 |
| `map-query` | 查询区域场景图 | `槽位`、`区域` |

完整行为参数以 [`../references/wuxia-rpg-actions.md`](../references/wuxia-rpg-actions.md) 为准，数据字段以 [`../references/wuxia-rpg-data-schema.md`](../references/wuxia-rpg-data-schema.md) 为准。

### 示例：玩家行为

```bash
python3 scripts/engine.py go <<'JSON'
{
  "槽位": 1,
  "行为": [
    {"类型": "查看线索"}
  ]
}
JSON
```

`行为`可以是一个数组。一次调用中的行为作为同一批次校验和提交。

### 示例：剧情裁定

```bash
python3 scripts/engine.py judge <<'JSON'
{
  "槽位": 1,
  "行为": [],
  "当前剧情": "沈听雪推开木门，屋内只余一盏将熄的油灯。",
  "场景要素": [
    {"主体": "油灯", "描写": "灯芯发黑，灯油将尽"}
  ]
}
JSON
```

`judge` 顶层只接受：

- `槽位`
- `行为`
- `当前剧情`
- `场景要素`
- `经历概括`

角色、线索、时间、关系度等变化必须放入 `行为` 数组，不能自创顶层字段。

### 示例：判定

```bash
python3 scripts/engine.py check <<'JSON'
{
  "槽位": 1,
  "属性": ["身法"],
  "判定角色": ["沈听雪"],
  "对抗": "@8",
  "基础成功率": 50
}
JSON
```

`check` 对外返回成功或失败及叙事提示，不暴露成功率和掷骰点数。有效判定会写入当前槽位的短期判定留痕，供后续 `judge` 检查叙事是否采用了判定结果。

### 示例：基础数据查询

未建档时可用槽位 `0` 查询冻结基线数据：

```bash
python3 scripts/engine.py query <<'JSON'
{
  "槽位": 0,
  "类型": "武学",
  "名称": "太乙玄门剑",
  "等级": 1
}
JSON
```

## 3. `go` / `judge` 两阶段协议

一个需要剧情推演的世界回合通常按以下顺序执行：

```text
玩家输入
  → GM 拆分主动行为
  → go 结算确定性成本与直接效果
  → 必要时 check / random-event
  → GM 推演剧情
  → judge 写入剧情结果与状态变化
  → 渲染返回界面
```

### `go`

`go`只承载玩家主动行为，例如移动、休息、交易、使用物品、配置、查询、存档和战斗操作。

- 确定性成本和直接效果在 `go` 内落盘；
- 同批行为任一项失败时，该批 `go` 不提交；
- `go` 不推进世界交互轮次，也不触发自动存档；
- 返回中存在 `界面` 时，调用方应直接渲染并停止，不再补调 `judge`；
- 返回中没有 `界面` 时，通常表示仍需 GM 推演并调用 `judge`。

### `judge`

`judge`承载 GM 推演后的叙事和状态变化。

- 同批状态变化先暂存在内存中；
- 任一变化非法时，本次 `judge` 整体不提交；
- 成功后统一写入角色、场景和探索状态；
- 只有成功返回 `exploration-ui` 的 `judge` 才推进世界交互轮次；
- 战斗触发、开始和推进可以成功结算，但不推进大世界轮次。

### 事务边界

`go`和`judge`是两个独立事务。

如果 `go` 已成功、随后 `judge` 失败，引擎只回滚本次 `judge` 的暂存变化，不会撤销已经提交的 `go` 结果。调用方应修正 `judge` 请求并重试，而不是重复执行 `go`。

## 4. 返回数据与界面路由

引擎返回普通 JSON 对象。常见字段包括：

| 字段 | 含义 |
|---|---|
| `界面` | 前端或 GM 应进入的界面类型 |
| `结算` | 本次成功或失败的结算条目 |
| `剧情描写` | 已写入的当前剧情 |
| `场景要素` | 当前可见对象及可用特殊指令 |
| `当前状态` | 队伍、位置、时间、体力、金钱等界面状态 |
| `槽位` | 当前存档槽位 |
| `saved` | 本轮是否产生自动存档 |
| `剩余` | 距下一次自动存档的交互轮数 |
| `错误` | 参数、规则或状态校验错误 |

`界面`是路由标识，不是已渲染文本。Markdown GM 按 `references/ui/` 中的规范渲染；Web 和 DSH 前端直接消费结构化字段。

## 5. 目录结构

```text
scripts/
├── engine.py                 # 统一 go/judge/check/query CLI 与库入口
├── settle/                   # 大世界结算编排、事务、字段和 UI 数据
├── common/                   # DAO、判定、状态、特效加载、时间工具
├── world/                    # 场景、地图、角色、交易、配装、武学与事件
├── combat/                   # 战斗状态机、ATB、AI、技能评分与战报
├── store/                    # explore、交换文件、快照和槽位持久化
├── effects/                  # 技能、状态、装备和物品动态脚本
└── tests/                    # 单元测试、契约测试与端到端测试
```

### `settle/`

| 模块 | 职责 |
|---|---|
| `engine_actions.py` | 行为处理器、成本结算和分发表 |
| `engine_fields.py` | `judge` 状态变化的校验与应用 |
| `engine_io.py` | 槽位切换、角色读写、当前状态组装、战斗临时文件管理 |
| `engine_ui.py` | 结构化界面响应与公共字段 |
| `engine_state.py` | 角色和场景的事务暂存区 |

### `common/`

| 模块 | 职责 |
|---|---|
| `dao.py` | 基线数据与槽位覆盖层的统一查询、派生和写入 |
| `check.py` | 属性判定与随机事件 |
| `status_manager.py` | 战斗和大世界共用的状态生命周期 |
| `effect_loader.py` | 动态加载技能、状态、物品和装备脚本 |
| `time_utils.py` | 世界时间换算与显示 |

### `world/`

| 模块 | 职责 |
|---|---|
| `scene.py` | 区域内场景图、场景人物和功能场景 |
| `map.py` / `map_query.py` | 跨区域地图与场景图查询 |
| `character_ops.py` | 角色字段变化、关系、死亡等操作 |
| `loadout.py` | 装备、主动武学、心法和战斗物品配置 |
| `mastery.py` | 武学精进与十境增益 |
| `trade.py` | 商人库存、买卖和价格结算 |
| `event.py` | 线索与事件视图 |

### `combat/`

- `battle_engine.py`：战斗状态机、ATB、命中、暴击、伤害、治疗、状态钩子和经验；
- `battle.py`：战斗 CLI、战斗运行时文件和战报组装；
- `ai_styles.py`：平衡、勇猛、谨慎等 AI 风格；
- `skill_scorer.py`：AI 候选行动评分。

正常集成应通过 `engine.py go/judge` 驱动战斗。`battle.py` 主要用于引擎内部调用和独立调试。

### `store/`

- `save_manager.py`：槽位、快照、自动存档和恢复；
- `explore_store.py`：`explore.json` 的收敛读写接口；
- `tips.py`：`go` 向 `judge` 传递机制变化摘要；
- `check_log.py`：短期判定留痕；
- `battle_last.py`：战斗操作与下一次 `judge` 之间的结算底稿；
- `events_store.py`：探索事件列表的数据入口。

## 6. 数据与持久化

### 基线数据

只读基线位于：

```text
wuxia-rpg/assets/data/
```

主要包含：

- `characters/`
- `skills/`
- `items/`
- `buffs/`
- `factions/`
- 地图、世界观和 NPC 初始位置等公共 JSON

发布包可以只提供 `assets/data.zip`。创建角色时，如果 `assets/data/` 不存在而压缩包存在，引擎会先还原基线目录。

### 槽位写时复制

每个正式角色使用独立槽位：

```text
<WUXIA_RPG_SAVE_DIR>/slot_<N>/
├── .data/                    # 被修改或新建的数据条目
├── meta.json                 # 角色名、创建时间、最近存档等元信息
├── explore.json              # 当前世界与叙事状态
├── merchant.json             # 当前商人货架缓存
├── map_overlay.json          # 运行时新增或改写的场景连接
├── scene_types_overlay.json  # 运行时功能场景类型
└── savefile_*.json           # 快照
```

DAO 读取时先查当前槽位的 `.data/`，未命中再回退到 `assets/data/`。写入只进入 `.data/`，不会修改基线。因此：

- 建档无需复制全部数据；
- 不同槽位可以共享同一套只读基线；
- 角色和世界修改彼此隔离；
- 快照只需保存相对基线的字段级差异。

不要在运行时直接修改 `assets/data/`，也不要绕过 DAO 修改 `.data/`。

JSON 文件存在但发生 IO、编码、语法或结构错误时会返回分类错误并停止权威状态写入；仅索引、商人缓存和短期交换文件会记录告警后按既定策略降级。

### `explore.json`

`explore.json` 是当前槽位的实时世界镜像，保存：

- 当前位置与当前时间；
- 体力和队伍；
- 当前剧情与场景要素；
- 经历概括；
- 线索及其进展；
- 状态提示；
- 世界交互轮次 `round`。

角色气血、内力、铜钱、经验、物品、装备和武学等角色数据由 `.data/` 中的角色覆盖文件维护，不应重复塞入 `explore.json`。

### 短期交换文件

槽位中还可能出现：

| 文件 | 生命周期 |
|---|---|
| `tips.json` | `go` 成功后写入；`judge` 成功消费后清除 |
| `check.json` | 保存最近若干轮判定留痕；读档时清除 |
| `battle_last.json` | 保存最近一次战斗操作底稿；战后清除 |

这些文件是跨 CLI 进程传递上下文的交换介质，不是长期游戏状态，也不应由调用方手工编辑。

战斗状态、元数据和战报位于 `slot_<N>/.runtime/battle/`，不随存档快照保存；无 slot 调试时使用 `WUXIA_RPG_RUNTIME_DIR/battle/` 或系统临时目录。

### 快照与自动存档

- 每个槽位最多保留 5 个快照；
- 超出上限时淘汰最早的快照；
- 建号后的首个探索回合创建“初入江湖”快照；
- 此后每 5 个成功的 `exploration-ui` 交互轮触发自动存档；
- 读档会根据冻结基线和快照差异重建 `.data/`，并同步探索、地图与商人状态。

## 7. 战斗与动态特效

战斗引擎维护：

- 参战者、队伍和操控方式；
- 充能、速度和行动顺序；
- 气血、内力、冷却和物品次数；
- 状态持续时间与钩子；
- AI 候选动作评分；
- 战局结果、经验结算和战报数据。

动态脚本目录：

```text
effects/
├── skills/       # 武学特效
├── status/       # 状态钩子
├── equipments/   # 装备特效
└── items/        # 物品特效
```

特效由 `common/effect_loader.py` 按名称加载并在进程内缓存。特效脚本可以修改战斗事件上下文或当前战斗内存状态，但必须服从战斗引擎生命周期：

- 不得自行写槽位文件；
- 不得绕过状态管理器伪造持久状态；
- 不得依赖已废弃的旧钩子名；
- 新增或修改钩子后必须补充契约测试。

独立查看角色派生战斗属性：

```bash
python3 scripts/combat/battle.py stats 骆逸
```

用固定随机种子调试 AI 战斗：

```bash
python3 scripts/combat/battle.py \
  --seed 7 \
  --允许逃跑 false \
  --teams '甲:陈挺之;乙:和悦' \
  陈挺之 和悦
```

参战角色必须存在于当前数据源中，队伍必须通过 `--teams` 明确指定。

## 8. 集成方式与并发约束

### CLI 子进程

Coding Agent 通常为每次调用启动一个 `engine.py` 子进程。stdin/stdout 是稳定边界，短期上下文通过槽位交换文件衔接。

### Python 模块

长驻服务也可以把 `scripts/` 加入模块搜索路径后导入：

```python
from pathlib import Path
import sys

sys.path.insert(0, str(Path("wuxia-rpg/scripts").resolve()))
import engine

result = engine.go(1, [{"类型": "查看线索"}])
```

但引擎内部包含进程级可变状态：

- DAO 当前数据目录及缓存；
- `settle.engine_state` 事务暂存区；
- 战斗运行时全局和临时文件。

因此，长驻进程必须使用一把覆盖全部槽位的全局锁串行调用引擎，不能只做“每槽位一把锁”。`engine_gateway.py` 统一持有该锁，`engine_service.py` 只处理 HTTP 与生命周期。

八个公开 operation 定义在 Skill 根目录的 `tools.json`，Web 与 DSH 均从 `/api/tools` 注册宿主工具。两者共用服务实现，但默认启动独立进程。多个进程同时写同一存档根目录仍可能发生竞争，应使用不同的 `WUXIA_RPG_SAVE_DIR`，或由更高层确保互斥。

### 渲染模式

`WUXIA_RPG_RENDER_MODULE` 会写入返回对象的 `渲染模式` 字段，供宿主选择文本或结构化展示。它不改变规则结算本身。

## 9. 扩展引擎

### 新增 `go` 行为

1. 在 `settle/engine_actions.py` 实现处理器；
2. 注册到行为分发表；
3. 明确体力、时间、事务和界面语义；
4. 更新 `references/wuxia-rpg-actions.md`；
5. 添加成功、失败和批次回滚测试。

处理器不应直接提交半成品角色状态。角色修改应进入事务暂存区，由外层统一提交。

### 新增 `judge` 状态变化

1. 在 `settle/engine_fields.py` 定义参数校验与应用逻辑；
2. 判断它是否需要角色、场景或探索状态事务；
3. 明确与既有变化同批失败时的回滚行为；
4. 更新行为契约和端到端测试。

### 新增数据条目

- 按现有 JSON schema 和目录分组添加；
- 角色、武学、物品等分组数据需保持对应 `index.json` 一致；
- 动态效果名必须与 `effects/` 下的脚本文件名一致；
- 不要把运行时角色或测试变更写回基线。

### 新增特效

1. 选择 `skills/`、`status/`、`equipments/` 或 `items/`；
2. 复用现有同类脚本的当前钩子签名；
3. 通过状态管理器处理持续状态；
4. 为事件上下文修改、层数、持续时间和清理路径添加测试。

## 10. 测试与调试

运行完整回归：

```bash
python3 scripts/tests/run_all_tests.py
```

该入口依次执行：

1. Python 源码编译；
2. `unittest` 与端到端测试；
3. `assets/data/` 全量 JSON 解析；
4. 废弃战斗钩子残留检查。

仅检查主入口语法：

```bash
python3 -m py_compile scripts/engine.py
```

调试引擎调用时应使用隔离存档目录：

```bash
WUXIA_RPG_SAVE_DIR=/tmp/wuxia-engine-test \
python3 scripts/engine.py go <<'JSON'
{"槽位": 1, "行为": [{"类型": "开始游戏"}]}
JSON
```

排查问题时优先检查：

1. CLI 的退出码、stdout JSON 和 stderr；
2. 返回中的 `错误`、`结算`和`界面`；
3. 对应槽位的 `explore.json` 与 `.data/`；
4. `tips.json`、`check.json`、`battle_last.json` 是否符合当前阶段；
5. 对应 slot 的 `.runtime/battle/` 中战斗状态与战报；
6. 是否存在并发调用或错误的 `WUXIA_RPG_SAVE_DIR`。

## 11. 相关文档

- [`../SKILL.md`](../SKILL.md)：GM 主循环与工具调用规则；
- [`../references/wuxia-rpg-actions.md`](../references/wuxia-rpg-actions.md)：行为和状态变化参数契约；
- [`../references/wuxia-rpg-data-schema.md`](../references/wuxia-rpg-data-schema.md)：数据结构；
- [`../references/wuxia-rpg-battle-system.md`](../references/wuxia-rpg-battle-system.md)：战斗系统；
- [`../references/ui/`](../references/ui/)：Markdown 界面渲染规范；
- [`../../docs/技术手册.md`](../../docs/技术手册.md)：完整项目架构与设计取舍。
