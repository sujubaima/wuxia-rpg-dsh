---
name: wuxia-rpg-trade-sell-ui
description: 出售界面：选定出售物品与数量
---

# trade-sell-ui 界面交互

`出售` 指定买家但未指定物品时返回本界面，正文由 engine 直出 `渲染文本`。

## 交互

- 价格为 engine 单件估价，总价由 engine 结算。
- 专用指令：出售 [物品] [数量]、返回游历。
- 「指令查询」先列上述专用指令，再读 [wuxia-rpg-common-commands.md](./wuxia-rpg-common-commands.md) 补充通用指令。
