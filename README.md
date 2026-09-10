# 武侠 RPG

一个由 Coding Agent / LLM 担任游戏主持人（GM）的文字武侠 RPG 套件。项目将规则、世界设定、结构化数据、数值引擎、存档系统与交互界面拆分为独立模块，可按需要选择以下运行方式：

| 方式 | 适用场景 | 需要的目录 |
|---|---|---|
| Coding Agent Skill | 在支持 Skill 与工具调用的 Coding Agent 中直接游玩 | `wuxia-rpg/` |
| DSH 插件 | 在 DeepSeek Harness（DSH）会话中使用武侠卡片、面板与战斗 UI | `wuxia-rpg/`、`dsh-plugin/`、`install.sh` |
| 自带 Web 套件 | 使用独立 Web UI，通过 agent-lite 连接模型 API 驱动 GM | `wuxia-rpg/`、`web/`、`agent/`、`config.json` |

当前 Skill 版本：`0.9.8`。

> [!WARNING]
> 当前项目仍处于初期阶段，代码实现、游戏机制与数值设计均有待持续打磨。后续版本不排除引入不兼容修改，当前版本仅供体验。

## 项目组成

```text
.
├── wuxia-rpg/              # 核心 Skill：规则、设定、数据、数值引擎与存档逻辑
│   ├── SKILL.md
│   ├── references/         # GM 规则、数据结构、战斗规则与 Markdown UI
│   ├── assets/data/        # 角色、武学、物品、状态、阵营与地图基线数据
│   └── scripts/            # go / judge / check / query 等引擎入口
├── web/                    # 标准库 HTTP/SSE 服务与原生、React Web UI
├── agent/                  # 纯 Python 标准库的 agent-lite 底座
├── dsh-plugin/             # DSH Host 工具、隐藏命令与 Client UI
├── dsh-preset/wuxia/       # 可移植武侠 GM Preset
├── config.json             # Web 套件配置
├── install.sh              # DSH 插件一键安装脚本
└── release.sh              # 完整套件打包脚本
```

`wuxia-rpg/assets/data/` 是发布和内容编辑的唯一权威数据源；`backup/history/` 中的数据目录仅作历史归档，不参与运行或发布。

存档默认写入 `~/.wuxia/save/slot_<N>/`，可通过环境变量修改。

## 环境要求

- Python 3.9 或更高版本。
- Skill 与引擎本身只使用 Python 标准库，无需安装 pip 依赖。
- 使用 DSH 插件时需已安装 DSH、pnpm；从源码构建还需 Node.js 18+ 与 npm。
- 所选模型需要具备稳定的工具调用、文件读取与长上下文能力。

---

## 一、作为 Coding Agent Skill 使用

### 1. 安装 Skill

必须完整保留 `wuxia-rpg/` 目录，不能只复制 `SKILL.md`；规则引用、数据文件和引擎脚本均通过相对路径加载。

Claude Code 用户级安装（复制到 `~/.claude/skills/`，若目标已存在请先自行确认覆盖或保留）：

```bash
mkdir -p ~/.claude/skills
cp -R /绝对路径/cc-game-dsh/wuxia-rpg ~/.claude/skills/
```

或使用符号链接，项目更新后立即生效：

```bash
mkdir -p ~/.claude/skills
ln -s /绝对路径/cc-game-dsh/wuxia-rpg ~/.claude/skills/wuxia-rpg
```

其他 Coding Agent：将 `wuxia-rpg/` 注册为该 Agent 的 Skill 目录，并确保 Agent 至少具有读取 Skill 文档与 `references/` 文件、执行 Python/Bash 命令并传入 stdin、对存档目录读写的能力。

### 2. 开始与使用

启动 Agent 后直接输入：

```text
开始游戏
```

也可以使用以下自然语言指令：

```text
开始大世界模拟
查看地图
查看背包
前往杭州城
挑战眼前的刀客
保存游戏
退出游戏
```

正常游玩无需手动调用引擎；该命令主要用于安装验证和调试。

### 3. 存档目录

默认存档位置：

```text
~/.wuxia/save/
```

自定义位置：

```bash
export WUXIA_RPG_SAVE_DIR=/绝对路径/wuxia-save
```

建议为不同部署实例设置不同存档目录，避免多个实例同时操作同一档位。

---

## 二、作为 DSH 插件使用

需先安装 Python 3 和 pnpm。安装器按顺序选择 DSH CLI：PATH 中的 `dsh` → `$DSH_HOME/profiles/node_modules/@deepseek-ai/dsh` 内置 CLI → `npx --yes @deepseek-ai/dsh`（需 Node.js 18+ 与 npm）。进入项目根目录执行：

```bash
chmod +x install.sh
./install.sh
```

脚本会自动：

1. 从源码构建插件，或校验发布包中的预构建产物；
2. 将带完整 Skill 的“武侠GM”Preset 安装到当前 `$DSH_HOME`；
3. 优先通过 `dsh` 接入插件；命令不在 PATH 时自动改用 `npx --yes @deepseek-ai/dsh`。

自定义 profile 或 DSH Home：

```bash
./install.sh --profile web --dsh-home /你的/dsh-home
```

安装后执行 `dsh web`；若没有全局命令，则执行 `npx --yes @deepseek-ai/dsh web`。选择“武侠GM”新建会话并输入“开始游戏”。若以后移动项目目录，请在新位置重新运行安装脚本以刷新插件链接。

---

## 三、部署自带 Web 套件与 agent-lite 底座

Web 套件提供完整浏览器界面、SSE 对话流和 `/api/engine` 兼容接口。Web 会启动独立的共享 Engine Service，并从 `wuxia-rpg/tools.json` 注册受限的 `wuxia_*` 工具。服务端及 agent-lite 均为 Python 标准库实现。

### 1. 准备目录

确保以下内容位于同一项目根目录：

```text
cc-game-dsh/
├── wuxia-rpg/
├── web/
├── agent/
└── config.json
```

### 2. 配置 `config.json`

环境变量优先级高于 `config.json`。推荐从以下配置开始：

```json
{
  "backend_mode": "llm",
  "server": {
    "host": "127.0.0.1",
    "port": 8000,
    "frontend": "old"
  },
  "paths": {
    "save_dir": "",
    "skill_dir": ""
  },
  "engine": {
    "service_url": "",
    "timeout_ms": 120000
  },
  "llm": {
    "base_url": "https://your-openai-compatible-endpoint.example/v1",
    "api_token": "",
    "model": "your-model"
  }
}
```

#### 通用配置

| 配置字段 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `backend_mode` | `LLM_BACKEND` | `llm` | GM 后端模式，默认 `llm`（agent-lite + 模型 API） |
| `server.host` | `HOST` | `127.0.0.1` | HTTP 监听地址 |
| `server.port` | `PORT` | `8000` | HTTP 监听端口 |
| `server.frontend` | `WUXIA_FRONTEND` | `old` | 使用原生 JavaScript 游戏界面 |
| `paths.save_dir` | `WUXIA_RPG_SAVE_DIR` | `~/.wuxia/save` | 存档根目录 |
| `paths.skill_dir` | `WUXIA_RPG_SKILL_DIR` | `项目根/wuxia-rpg` | Skill 目录 |
| `engine.service_url` | `WUXIA_RPG_ENGINE_URL` | 空 | 外部 Engine Service；为空时自动启动独立实例 |
| `engine.timeout_ms` | `WUXIA_RPG_ENGINE_TIMEOUT_MS` | `120000` | 引擎请求超时 |

#### `llm` 后端

`llm` 模式使用 `agent/` 中的 agent-lite，直接连接 OpenAI 兼容接口。

| 配置字段 | 环境变量 | 说明 |
|---|---|---|
| `llm.base_url` | `AGENT_API_BASE` | OpenAI 兼容接口地址，通常包含 `/v1` |
| `llm.api_token` | `AGENT_API_TOKEN` | Bearer Token；服务不要求鉴权时可留空 |
| `llm.model` | `AGENT_MODEL` | 模型名称 |

Web 的 agent-lite 只注册 `use_skill`、八个 `wuxia_*` 工具和受限的 `wuxia_read_reference`，不提供通用 `read/write/bash/list`。`claude` 后端仍受 Claude Code 自身权限模式约束。

### 3. 启动

从项目根目录执行：

```bash
python3 web/server.py
```

临时使用环境变量覆盖配置的示例：

```bash
HOST=127.0.0.1 PORT=9000 LLM_BACKEND=llm \
AGENT_API_BASE=http://127.0.0.1:8646/v1 \
AGENT_MODEL=your-model \
python3 web/server.py
```

### 4. 访问与使用

| 地址 | 界面 |
|---|---|
| `http://127.0.0.1:8000/` | 原生 JavaScript 游戏界面 |
| `http://127.0.0.1:8000/game` | 原生 JavaScript 游戏界面 |
| `http://127.0.0.1:8000/ui/vanilla/classic` | 经典聊天界面 |
| `http://127.0.0.1:8000/api/health` | 服务健康检查 |

打开页面后输入“开始游戏”，即可新建角色、读取存档并进入游历。浏览器会保存会话 ID；游戏进度独立保存在 `WUXIA_RPG_SAVE_DIR` 中。

`llm` 后端的对话上下文保存在服务进程内存中，服务重启后会话上下文丢失，但游戏存档不受影响。

### 5. 生产部署建议

- 仅本机使用时，将 `server.host` 设为 `127.0.0.1`。
- 对外提供服务时，建议在前方部署带鉴权、HTTPS、请求大小限制和超时控制的反向代理。
- 不要把模型 API Token 提交到版本库；生产环境优先通过环境变量或密钥管理服务注入。
- 不建议多个 Web/DSH 实例同时写同一个存档目录。

---

## 常见问题

### Skill 未触发或提示找不到 `wuxia-rpg`

检查目录层级是否为：

```text
<skills 根目录>/wuxia-rpg/SKILL.md
```

并确认复制的是完整目录。DSH 一键安装后还可检查 `$DSH_HOME/.agent-presets/wuxia/skills/wuxia-rpg/SKILL.md`；随后重启或新建会话，让 Skill 重新扫描。

### Web 的 `llm` 后端无响应

核对启动日志中的 `AGENT_API_BASE`、`AGENT_MODEL` 和 Token 状态，并确认模型服务支持 OpenAI 兼容的聊天与工具调用协议。

### 修改配置后没有生效

环境变量优先于 `config.json`。先检查当前 shell、systemd、容器或反向代理配置中是否已经设置同名环境变量。

## 进一步文档

- 核心 GM 规则：[`wuxia-rpg/SKILL.md`](./wuxia-rpg/SKILL.md)
- Web 套件说明：[`web/README.md`](./web/README.md)
- agent-lite 说明：[`agent/README.md`](./agent/README.md)
- 玩家手册：[`docs/玩家手册.md`](./docs/玩家手册.md)
- 详细规则：[`docs/详细规则.md`](./docs/详细规则.md)
