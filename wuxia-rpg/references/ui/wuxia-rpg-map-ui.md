---
name: wuxia-rpg-map-ui
description: 场景地图界面：查看邻接图与已知地点
---

# map-ui 界面交互

`查看地图` 返回本界面，正文（邻接图、驿站出口、已知地点）由 engine 直出 `渲染文本`。

## 交互

- 只按 engine 返回的地图执行，不替玩家规划路线或选择目的地。
- 专用指令：前往地点、返回游历。
- 「指令查询」先列上述专用指令，再读 [common-commands.md](./wuxia-rpg-common-commands.md) 补充通用指令。
