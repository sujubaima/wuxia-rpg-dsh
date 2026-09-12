---
name: wuxia-rpg-item-ui
description: 配置战斗物品界面：携带消耗品的装卸与替换
---

# item-ui 界面交互

`配置物品` 打开或装、卸、换后返回本界面，正文由 engine 直出 `渲染文本`。

## 交互

- 只展示战斗可用消耗品，最多携带4类。
- 专用指令：携带 [物品]、卸下 [物品]、替换 [新物品] [原物品]、返回游历。
- 「指令查询」先列上述专用指令，再读 [wuxia-rpg-common-commands.md](./wuxia-rpg-common-commands.md) 补充通用指令。
