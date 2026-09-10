---
name: wuxia-rpg-travel-ui
description: 驿站出行界面：选择直达目的地
---

# travel-ui 界面交互

在驿站调用未指定目的地的 `远行（舟车）` 返回本界面，正文由 engine 直出 `渲染文本`。

## 交互

- 玩家选定后再带目的地调用 `远行（舟车）`；只按 engine 返回的直达路线执行，不替玩家规划中转或选择目的地。
- 专用指令：前往 [目的地]、返回游历。
- 「指令查询」先列上述专用指令，再读 [common-commands.md](./wuxia-rpg-common-commands.md) 补充通用指令。
