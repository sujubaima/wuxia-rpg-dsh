---
name: wuxia-rpg-equip-ui
description: 配置装备界面：五个装备槽的穿脱
---

# equip-ui 界面交互

`配置装备` 打开或穿/脱后返回本界面，正文由 engine 直出 `渲染文本`。

## 交互

- 专用指令：装备 [物品] [槽位]、卸下 [槽位]、返回游历。
- 剑法、刀法、长兵、奇门、暗器须有任一武器槽类型匹配；搏击不受武器限制。
- 「指令查询」先列上述专用指令，再读 [wuxia-rpg-common-commands.md](./wuxia-rpg-common-commands.md) 补充通用指令。
