---
name: wuxia-rpg-save-ui
description: 游戏内读档界面：当前槽位存档点的选择与返回
---

# save-ui 界面交互

游戏进行中调用 `存档列表` 返回本界面，正文由 engine 直出 `渲染文本`（仅列当前 slot 的存档点）。该流程不同于 title-ui 的全部 slot 浏览，不复用标题态调用或跳转。

## 交互

- 玩家选择 File_N 后，以该存档目标调用 `加载存档`，返回 exploration-ui。
- 玩家选择返回时调用 `返回游戏` 回放当前 exploration-ui；不返回标题页，也不浏览其他 slot。
- 「指令查询」读 [common-commands.md](./wuxia-rpg-common-commands.md) 展示适用通用指令。
