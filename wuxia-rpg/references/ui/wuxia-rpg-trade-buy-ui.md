---
name: wuxia-rpg-trade-buy-ui
description: 购买界面：选定货架物品与数量
---

# trade-buy-ui 界面交互

`购买` 指定卖家但未指定物品时返回本界面，正文由 engine 直出 `渲染文本`。

## 交互

- 按 engine 返回的库存和价格执行，不自行增删或改价。
- 专用指令：购买 [物品] [数量]、返回游历。
- 「指令查询」先列上述专用指令，再读 [common-commands.md](./wuxia-rpg-common-commands.md) 补充通用指令。
