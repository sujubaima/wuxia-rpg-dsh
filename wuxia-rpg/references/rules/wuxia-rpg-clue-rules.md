---
name: wuxia-rpg-clue-rules
description: 武侠RPG 线索创建、事实推进、扩展、结算与奖励规则。涉及线索时读取
---

# 线索系统

## 一、基本原则

- 玩家界面仍称“线索”；GM 用任务蓝图描述其隐藏结构。
- GM 只提交已经发生并确认的事实，不直接指定“进入某阶段”。
- engine 依据事实自动完成节点、发放奖励、关闭线索并更新线索栏。
- `go` 的 `action.player.completed` 只表示动作已执行；调查成功、说服成立等叙事结果须在 plot-writing 中提交事实，由 judge 落盘。
- `任务摘要及进度` 是玩家投影，不是权威状态；不得直接编辑或重传整条线索。
- 新档自动载入 `assets/data/quests/` 下全部预设故事线并保持隐藏；起始节点条件满足时只提示 GM，实际呈现引子后再用 `线索-发现` 公开。

线索生命周期：隐藏 → 进行中 → 已结束。

## 二、何时创建

信息浮出即入栏，无需玩家接取。一次性情报并入既有线索；无既有线索可并入的一次性情报，记入经历概括即可，不单独建栏。可持续推进的委托、冲突或悬案才创建新线索，满足以下任一即视为此类，应当轮建栏：

- 事件尚未解决，且情报中含至少一个可继续调查的方向（可寻访的当事人/地点/实物、明确的涉事方、委托或托付）；
- 情报之间已构成矛盾或疑点（如“旧水寨不害命”与“满船人失踪”并存）。

仅为背景铺陈、无追查方向的见闻（天下大势、风土人情、他人转述的旧闻）不建线索。新档场景中若无可并入的既有线索，符合上述标准的情报直接当轮建栏，不得以“传闻未成形”“玩家未表露兴趣”为由推迟。

正例：船工细述两艘货船失踪经过——未解事件，有可寻访的船家货主，建线索。反例：酒客闲聊近年米价——风土人情，无追查方向，不建。

即兴线索首次出现时，判定与随机结果明确后先提交 plot-writing，再用 `quest-prepare` 一次性批量准备蓝图，由同轮 judge 全部采用。蓝图至少包含：

- 存档内唯一且创建后不可修改的名称、引子和隐藏目标；
- 单一初始节点加一级后继（逐级生长）：一级后继不得再带后继节点，各须为终局或扩展点，分支数不限；后续推进一律经扩展逐级补齐；
- 至少一个未触发的扩展点（生长芽），至少一个玩家可执行的当前方向；
- 条件所需的事实定义；每条须有一句非空描述，供 GM 识别候选事实；
- 条件必须锚定具体、可确认的事实——地点、门派、人物或明确的剧情事实；「查明真相」这类宽泛事件、「一时查不清」这类模糊状态都不可设为条件，事实未定时留扩展点，确认后经扩展补路径；
- 每个节点显式填写 `关闭条件`、`关闭描述`；不用时两者均为 `null`；
- 各可见节点的完成摘要；
- 稳定奖励 ID，或明确无奖励。

未来不确定内容可留为显式扩展点，但不得留下无后继、无终局、非扩展点的断头节点。

设计蓝图时条件先行，按序落笔：

1. 先列本轮可能确认的可观察事件或属性，如「取得账册」「听到证词」「知情者死亡」「文书被毁」；不要先造「此路未通」「真相已明」等结论状态；
2. 每项使用闭集主体/谓词分配事实键写入 `事实定义`；较高层结论由节点条件中的 `all/any` 组合具体事实，不另建结论谓词；
3. 事实键与节点互为覆盖：每个事实键至少被一个节点消费，每个节点条件至少引用一个事实键，双向不空才算画完；
4. 本轮能形成明确节点结果的写 `终局:true` 加条件；尚无具体条件的写 `扩展点:true`，且只挂它自己，不顺带给其他无条件的终局；
5. 每级只推进一步：本轮写「取得/听到/目击了什么」，下一轮经扩展再写「据此如何行动」。

提交 `quest-prepare` 前自检：终局节点的条件都有事实键引用，没有则降级为扩展点；事实键都有节点消费，没有则删键或加节点；从起始节点出发的每条判定路径都能被本轮剧情命中；不设「什么都没查清就结案」的节点。

`quest-prepare` 不创建正式线索、不改事实或奖励；失败可修正后重试，首次成功后本轮不得覆盖，只有最终 `judge` 成功才生效。

## 三、事实规则

事实键格式：

```text
<subject>.<predicate>@<scope>
```

谓词是闭集，不得临时造词或把结论塞入主体 ID。正例：

```text
item:ledger_001.authenticity@world
item:ledger_001.authenticity@character:掌柜
scene:旧宅.accessible@world
character:witness.dead@world
information:ledger-case:testimony.heard@player
```

反例：

```text
case:foo.truth-known@world
information:foo:truth.discovered@world
quest:foo.impossible@world
information:foo:evidence.enough@world
```

`truth/known/unknown/confirmed/verified/possible/impossible/enough/sufficient/progress/stage/state/status/value/resolved/solved/complete/ready/clue/evidence` 等宏观结论词不得作为谓词或主体 ID 词元；机械谓词 `skill:<skill-id>:known` 是唯一的 `known` 例外。`status` 只可作为条件比较符。

### 主体族与谓词

| 主体族 | 允许的叙事谓词 | 值类型 |
|--------|----------------|--------|
| `character:<id>` | `exists/location/identity/origin/affiliation/role/stance/present/alive/dead/captured/escaped/freed/contact/in_party` | 按属性为 bool、number 或 string/entity/enum |
| `item:<id>` | `exists/location/owner/source/destination/origin/authenticity/integrity/quantity/available/discovered/obtained/read/examined/delivered/destroyed` | 按属性为 bool、number 或 string/entity/enum |
| `document:<id>` | `exists/location/owner/source/destination/origin/authenticity/available/discovered/obtained/read/examined/delivered/destroyed` | bool 或 string/entity/enum |
| `information:<id>` | `source/destination/origin/identity/owner/target/terms/authenticity/quantity/available/linked/discovered/obtained/read/heard/witnessed/examined/delivered/destroyed` | bool、number、string/entity/enum；`terms` 也可为 set |
| `scene:<id>` | `exists/location/presence/discovered/accessible/visited/examined/opened/closed/guarded` | bool、string/entity；`presence` 也可为 enum |
| `faction:<id>` | `exists/location/controller/affiliation/stance` | bool 或 string/entity/enum |
| `choice:<quest-id>:<ending-id>` | `selected` | bool |
| `quest:<quest-id>` | `outcome` | enum |

引擎机械事实还固定允许：`party.stamina`、`world.time`、`player.location`、`player.region`、`character:<id>.copper/hp/mp/relation`，以及动态格式 `character:<id>.item:<item-id>:quantity`、`character:<id>.skill:<skill-id>:known/level`。不得把这些谓词移用到其他主体族。

终局条件使用 `choice:<quest-id>:<ending-id>.selected@world == true` 等具体选择事实；终局 effect 再写 `quest:<quest-id>.outcome@world`。同一任务不得把自己的 `outcome` 反过来作为完成或关闭依据。

### 比较符与未知值

| 比较符 | 允许类型 | 约束 |
|--------|----------|------|
| `eq/ne` | 全部 | 期望值必须符合事实定义；set 按规范化后的集合比较 |
| `in` | bool/enum/number/string/entity | 必须是非空数组，每项均符合定义；不用于 set |
| `gt/gte/lt/lte` | number | bool 不视为 number |
| `exists` | 全部 | 操作数必须为 bool；任务条件禁止 `exists:false` 及 `not(exists:true)` 等价写法 |
| `status` | 全部 | 仅允许 `unknown/alleged/verified/refuted` |

缺少记录，或记录状态为 `unknown/alleged` 时，值比较结果是 UNKNOWN，不是 FALSE。因此 `not(UNKNOWN)` 仍为 UNKNOWN，不会触发节点；不得用 `not(尚未记录的事实)` 表达“已确认无法查明”。实体确实不存在时，应注册 `.exists` bool 事实并在剧情确认后写入 `false`。

- 客观真相、NPC 说法、传闻和角色认知必须使用不同 scope，不得混写。
- 已确认事实冲突时，普通 `事实` 写入会被拒绝；确需揭示误认、调包或设定修订时，用 `事实-修订` 并写明原因。
- 创建与扩展只校验蓝图结构和事实定义，不按当前事实值检查终局可达性或枚举结果覆盖。
- 实际事实写入仍须遵守主体族、谓词、类型、互斥和显式修订规则；任务蓝图不能绕过这些约束。

## 四、推进与扩展

### 推进

剧情确认了任务语义结果时，在 plot-writing 的 `行为` 中提交 `事实`，judge 统一落盘并推进相关线索。

机械事实（时间、体力、位置、持有物、关系度、生死等）由既有状态变更事件自动维护；GM 不重复写。

节点完成后：

1. engine 记录稳定节点 ID；
2. 同批执行节点效果与奖励；
3. 全部成功提交后，线索栏才显示完成摘要；
4. 任一奖励或触发失败，则节点、奖励和摘要一并不提交。

已完成节点和已领取奖励不会因后续事实修订而撤销。

### 路径关闭

节点前置满足后先判断 `关闭条件`，再判断 `完成条件`。关闭条件成立时显示 `关闭描述`，不执行正常效果和奖励，并阻断该节点发出的推进路径；`{}` 表示到达后无条件关闭该支路。

- `all` 汇合任一必需路径关闭即阻断；`any` 汇合仅在所有路径关闭后阻断。
- 上游阻断的节点不显示摘要。
- 路线关闭必须引用具体阻断事实，例如 `character:witness.dead == true`、`document:ledger.destroyed == true` 或 `information:case:witness-source.available == false`；只有证人已死、文书已毁或来源已明确不可达时才能写入。不得创建「无法查明」「线索断绝」等结论事实。
- 完成、关闭和阻断均不可自动恢复；出现转机时扩展新路径。
- 所有路径均完成、关闭或阻断且未触发终局时，线索自动结束。

### 扩展与关闭

进入扩展点前，GM 须在 plot-writing 后以 `quest-prepare.任务` 一次性准备“扩展”或“关闭”，由 judge 自动采用。

扩展（逐级生长）：

- 指定原 `名称` 和 `扩展点`，不得改名；
- 版本递增；
- 新增节点一律为该扩展点的一级后继：前置须且仅须该扩展点、不得再带后继节点，各须为终局或扩展点；分支数不限；
- 不得删除或改写已完成、已关闭节点、历史摘要和已领取奖励；已激活、已关闭或阻断的扩展点不可再扩展。

关闭（弃线）：

- 该方向无继续推演必要时，可用「关闭」操作强关未激活扩展点，不增后继；
- 蓝图仅 `名称`、`节点`、`描述`；`描述` 必填非空，作为玩家可见的关闭文案；
- 任务须进行中，扩展点须未激活、未关闭；关闭不可恢复，后续转机走新扩展或新线索。

## 五、节点与奖励

完成摘要只写玩家已经获知的客观进展，不剧透隐藏目标、未满足条件或预设结局。只有实质进展才设可见节点：新情报、关键转折、阶段成果、明确下一步或终局。

经验参考：

- 过渡/小节点：200～600
- 常规节点：800～1500
- 关键节点：1800～3000
- 解决/关闭节点：3000～5000

奖励随节点一次性结算；含状态变更的奖励须有稳定 `奖励ID`。自然移动、寒暄、重复确认和无成果的失败判定不发奖励。奖励结算失败且本轮尚未准备任务草稿时，可用 `quest-prepare`「修改」未完成节点的奖励，再重调 judge；草稿由 judge 自动采用。

## 六、GM 提示

engine 返回 `GM线索提示` 时：

- `潜在线索变化`：本轮动作可能对应未确认事实；剧情确已成立时才在 plot-writing 提交。提示只提供事实候选，不决定是否建栏；建栏仍按「何时创建」判断。
- `任务扩展`：线索抵达扩展前沿时，plot-writing 后用 `quest-prepare` 一次性准备扩展；不再推进的方向可用「关闭」操作，judge 会自动采用。
- `隐藏线索`：隐藏线索入口条件已满足；叙事时机合适时，在 plot-writing 中以 `线索-发现` 公开，由 judge 落盘。

这些提示仅供 GM 使用，不得直接展示给玩家，也不得当作已经完成的线索进展。

具体 JSON 契约见 [wuxia-rpg-actions.md](../wuxia-rpg-actions.md)。
