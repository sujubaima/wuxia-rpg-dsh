# 武侠RPG Web 聊天

一个与 GM 对话的聊天页面。支持两种 LLM 后端（`LLM_BACKEND` 全局切换）：

- `agent`（默认）——直接调用 `../agent` 目录下的 agent-lite（`core.Agent`），进程内运行，模型由 `AGENT_API_BASE`/`AGENT_MODEL` 决定（见 `agent/README.md`）；
- `claude`——桥接 headless `claude -p`，自动继承项目 `CLAUDE.md` 与 `wuxia-rpg` 技能。

## 启动

```bash
python3 web/server.py                     # agent 后端，默认
LLM_BACKEND=claude python3 web/server.py  # claude 后端
# 默认 http://127.0.0.1:8000
```

浏览器打开页面即可聊天。首次输入「开始游戏」即触发标题界面分流。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | 8000 | 监听端口 |
| `HOST` | 127.0.0.1 | 监听地址 |
| `LLM_BACKEND` | agent | LLM 后端：`agent` \| `claude` |
| `CLAUDE_BIN` | claude | claude CLI 路径 |
| `CLAUDE_PERMISSION_MODE` | auto | claude 后端权限模式 |
| `AGENT_API_BASE` / `AGENT_MODEL` | — | agent 后端模型服务 |
| `WUXIA_RPG_ENGINE_URL` | 空 | 外部 Engine Service；为空时自动启动独立实例 |
| `WUXIA_RPG_ENGINE_TIMEOUT_MS` | 120000 | 引擎请求超时 |
| `WUXIA_RPG_ENGINE_PORT` | 0 | 自动启动实例的端口；`0` 表示动态分配 |

## 引擎与权限

Web 和 DSH 共用 `wuxia-rpg/scripts/engine_service.py` 实现，但默认各自启动独立进程。工具定义来自 `wuxia-rpg/tools.json`，全部经 `EngineGateway` 串行分发。

`agent` 后端只注册八个 `wuxia_*` 工具和受限的 `wuxia_read_reference`，不提供通用 `read/write/bash/list`。`claude` 后端仍由 `CLAUDE_PERMISSION_MODE` 控制 Claude Code 权限。

## 会话

- `session_id` 存于浏览器 `localStorage`，跨刷新续接同一对话。
- 「新对话」按钮清空并开启新会话。
- claude 后端：服务端用 `.sessions.json` 记录已创建会话，区分 `--session-id`（新建）与 `--resume`（续接）。
- agent 后端：会话按 `session_id` 存于服务进程内存，服务重启即失。

## 文件

- `server.py` — stdlib HTTP + SSE 后端
- `engine_client.py` — Engine Service 生命周期与调用客户端
- `wuxia_tools.py` — Schema 驱动的受限工具注册
- `index.html` — 聊天 UI（水墨武侠主题）
