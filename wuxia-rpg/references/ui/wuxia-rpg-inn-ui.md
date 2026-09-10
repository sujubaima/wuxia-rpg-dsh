---
name: wuxia-rpg-inn-ui
description: 客栈休息界面：选择休息等级
---

# inn-ui 界面交互

玩家在客栈表达投宿意图且未指定完整休息参数时返回本界面，正文由 engine 直出 `渲染文本`。露宿不使用本界面。

## 交互

- 玩家选择后，以该等级、`时长:32` 及场景裁定的 `免费` 参数调用 `休息`；不替玩家选择。
- 专用指令：休息 [等级]、返回游历。
- 「指令查询」先列上述专用指令，再读 [common-commands.md](./wuxia-rpg-common-commands.md) 补充通用指令。
