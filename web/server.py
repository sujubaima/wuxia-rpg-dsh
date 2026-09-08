#!/usr/bin/env python3
"""武侠RPG Web 聊天后端。

两种 LLM 后端（顶层 backend_mode / 环境变量 LLM_BACKEND 切换）:
- llm   : 直接走 LLM 请求后端（agent-lite，../agent 下 core.Agent），
  进程内运行，按 session_id 在内存中维护会话（重启即失）。模型由
  AGENT_API_BASE / AGENT_MODEL 决定。
- claude: headless `claude -p` 桥接 Claude Code，自动继承项目 CLAUDE.md
  与 wuxia-rpg 技能，权限走 --permission-mode。响应以 SSE 流式回推。

用法:
    python3 web/server.py                 # 默认 127.0.0.1:8000
    PORT=9000 python3 web/server.py
环境变量:
    PORT                    监听端口 (默认 8000)
    HOST                    监听地址 (默认 127.0.0.1)
    LLM_BACKEND             LLM 后端: llm | claude (默认 llm)
    AGENT_API_BASE / AGENT_API_TOKEN / AGENT_MODEL   llm 后端模型服务
    CLAUDE_COMMAND          claude 后端命令 (默认 claude)
    CLAUDE_PERMISSION_MODE  claude 后端权限模式 (默认 auto)
"""
import json
import os
import subprocess
import sys
import threading
import uuid
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine_client import EngineClient, EngineClientError
from wuxia_tools import WEB_SKILL_USAGE_NOTE, build_wuxia_registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # cc-game 根
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
# 原生前端位于 web/ui/vanilla，访问前缀 /ui/vanilla
OLD_DIR = os.path.join(WEB_DIR, "ui", "vanilla")
GAME_INDEX = os.path.join(OLD_DIR, "game.html")
CLASSIC_INDEX = os.path.join(OLD_DIR, "classic.html")
STATIC_DIR = os.path.join(OLD_DIR, "static")
# React 版前端生产构建产物（web/ui/react/dist），经 /ui/react 托管。未构建时该目录不存在，返回提示。
UI_DIR = os.path.join(WEB_DIR, "ui", "react", "dist")
_STATIC_MIME = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                ".html": "text/html; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
                ".json": "application/json; charset=utf-8", ".woff2": "font/woff2", ".woff": "font/woff"}
AGENT_DIR = os.path.join(ROOT, "agent")
SKILL_DIR = os.path.join(ROOT, "wuxia-rpg")

# Web 与 agent-lite 均经共享 Engine Service 调用确定性引擎。
_engine_client = None
_tools_manifest = None
ENGINE_SERVICE_URL = os.environ.get("WUXIA_RPG_ENGINE_URL", "")
ENGINE_TIMEOUT_MS = int(os.environ.get("WUXIA_RPG_ENGINE_TIMEOUT_MS", "120000"))
ENGINE_PORT = int(os.environ.get("WUXIA_RPG_ENGINE_PORT", "0"))

# 默认前端：new=React(/ui/react)，old/vanilla→原生前端(/ui/vanilla)。由 config.json server.frontend 配置。
DEFAULT_FRONTEND = os.environ.get("WUXIA_FRONTEND", "new")

BACKEND = os.environ.get("LLM_BACKEND", "llm").strip().lower()
PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "auto")
CLAUDE_COMMAND = os.environ.get("CLAUDE_COMMAND", "claude")

# llm 后端 (直接走 LLM 请求, agent-lite)
_LLM_BACKENDS = {"llm"}
# claude 后端 (走 claude -p 管道 SSE)
_CLAUDE_BACKENDS = {"claude"}


def _is_llm_backend():
    """当前是否走 LLM 请求后端 (agent-lite 直接调模型)。"""
    return BACKEND in _LLM_BACKENDS


def _resolve_backend_config():
    """在 _load_config 填充环境变量后, 刷新模块级后端配置常量。"""
    global BACKEND, PERMISSION_MODE, CLAUDE_COMMAND
    BACKEND = os.environ.get("LLM_BACKEND", "llm").strip().lower()
    PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "auto")
    CLAUDE_COMMAND = os.environ.get("CLAUDE_COMMAND", "claude")


def _resolve_engine_config():
    """刷新共享 Engine Service 的连接配置。"""
    global ENGINE_SERVICE_URL, ENGINE_TIMEOUT_MS, ENGINE_PORT
    ENGINE_SERVICE_URL = os.environ.get("WUXIA_RPG_ENGINE_URL", "").strip()
    ENGINE_TIMEOUT_MS = int(os.environ.get("WUXIA_RPG_ENGINE_TIMEOUT_MS", "120000"))
    ENGINE_PORT = int(os.environ.get("WUXIA_RPG_ENGINE_PORT", "0"))


def _resolve_paths():
    """在 _load_config 填充环境变量后, 刷新技能包路径。

    config.json paths.skill_dir (或环境变量 WUXIA_RPG_SKILL_DIR) 指定 wuxia-rpg 技能包
    路径; 未设则回退默认 (项目根/wuxia-rpg)。存档根目录 paths.save_dir (WUXIA_RPG_SAVE_DIR)
    由随后启动或连接的共享 Engine Service 读取。
    """
    global SKILL_DIR
    SKILL_DIR = os.environ.get("WUXIA_RPG_SKILL_DIR") or os.path.join(ROOT, "wuxia-rpg")
APPEND_SYS = (
    "你处于武侠RPG项目环境。严格遵循 ./wuxia-rpg/SKILL.md 的规则与指令分流，"
    "扮演武侠RPG的GM，禁止向玩家展示思考/分析/过渡过程。"
    "玩家已进入 wuxia-rpg 游戏会话：此后玩家输入原则上都是游戏指令，"
    "按 SKILL.md 的游戏规则与指令规则判断合法性并执行，不得当作普通闲聊处理。"
)
AGENT_SYS = (
    APPEND_SYS +
    "\n工作方式: 需要规则、结算、判定或查询时主动调用已注册的 wuxia_* 工具，不要编造数据；"
    "需要技能时先用 use_skill 加载完整指令；完成后直接给出面向玩家的最终回复。"
    "\n工具使用纪律: 仅使用武侠引擎工具与 wuxia_read_reference，不得尝试访问其他文件或运行命令。"
)

# 会话是否已创建（用于区分 --session-id 创建 与 --resume 续接）
_lock = threading.Lock()
_known = set()
_STATE = os.path.join(WEB_DIR, ".sessions.json")


def _load_state():
    global _known
    try:
        with open(_STATE, "r", encoding="utf-8") as f:
            _known = set(json.load(f))
    except (OSError, ValueError):
        _known = set()


def _load_config():
    """读取项目根 config.json, 填充两个后端读取的环境变量。

    环境变量优先 (已设置则保留), config.json 仅补缺。
      backend_mode  -> LLM_BACKEND (顶层, llm | claude)
      llm 段        -> AGENT_API_BASE / AGENT_API_TOKEN / AGENT_MODEL (llm 后端)
      claude 段     -> CLAUDE_COMMAND / CLAUDE_PERMISSION_MODE (claude 后端)
      server 段     -> HOST / PORT (本地监听地址) / WUXIA_FRONTEND (前端选择)
      paths 段      -> WUXIA_RPG_SAVE_DIR (存档根目录) / WUXIA_RPG_SKILL_DIR (技能包路径)
      engine 段     -> WUXIA_RPG_ENGINE_URL / WUXIA_RPG_ENGINE_TIMEOUT_MS
    """
    cfg_path = os.path.join(ROOT, "config.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f) or {}
    except (OSError, ValueError) as e:
        print(f"[config] 读取 {cfg_path} 失败 ({e}), 使用环境变量默认值。")
        return
    if not isinstance(cfg, dict):
        return
    # 顶层 backend_mode -> LLM_BACKEND
    mode = cfg.get("backend_mode")
    if mode and "LLM_BACKEND" not in os.environ:
        os.environ["LLM_BACKEND"] = str(mode)
    llm = cfg.get("llm", {})
    for env_key, cfg_key in (("AGENT_API_BASE", "base_url"),
                             ("AGENT_API_TOKEN", "api_token"),
                             ("AGENT_MODEL", "model")):
        val = llm.get(cfg_key)
        if val and env_key not in os.environ:
            os.environ[env_key] = str(val)
    claude = cfg.get("claude", {})
    for env_key, cfg_key in (("CLAUDE_COMMAND", "command"),
                             ("CLAUDE_PERMISSION_MODE", "permission_mode")):
        val = claude.get(cfg_key)
        if val and env_key not in os.environ:
            os.environ[env_key] = str(val)
    server_cfg = cfg.get("server", {})
    for env_key, cfg_key in (("HOST", "host"), ("PORT", "port"),
                             ("WUXIA_FRONTEND", "frontend")):
        val = server_cfg.get(cfg_key)
        if val and env_key not in os.environ:
            os.environ[env_key] = str(val)
    # 刷新默认前端：config.json server.frontend 生效后更新模块级常量
    global DEFAULT_FRONTEND
    DEFAULT_FRONTEND = os.environ.get("WUXIA_FRONTEND", "new")
    paths = cfg.get("paths", {})
    for env_key, cfg_key in (("WUXIA_RPG_SAVE_DIR", "save_dir"),
                             ("WUXIA_RPG_SKILL_DIR", "skill_dir")):
        val = paths.get(cfg_key)
        if val and env_key not in os.environ:
            os.environ[env_key] = str(val)
    engine_cfg = cfg.get("engine", {})
    for env_key, cfg_key in (("WUXIA_RPG_ENGINE_URL", "service_url"),
                             ("WUXIA_RPG_ENGINE_TIMEOUT_MS", "timeout_ms")):
        val = engine_cfg.get(cfg_key)
        if val not in (None, "") and env_key not in os.environ:
            os.environ[env_key] = str(val)
    print(f"[config] 已加载 {cfg_path} "
          f"(backend_mode={mode}, base_url={os.environ.get('AGENT_API_BASE', '(未设置)')}, "
          f"model={os.environ.get('AGENT_MODEL', '(未设置)')}, "
          f"token={'已设置' if os.environ.get('AGENT_API_TOKEN') else '无'}, "
          f"claude_command={CLAUDE_COMMAND})")


def _save_state():
    try:
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump(sorted(_known), f)
    except OSError:
        pass


def _mark_known(sid):
    with _lock:
        if sid not in _known:
            _known.add(sid)
            _save_state()


def _is_known(sid):
    with _lock:
        return sid in _known


def _jsonable(obj):
    """engine 返回偶含中文 ASCII 描图（标题页），用 ensure_ascii=False 直出即可；
    此钩子仅作显式标记，保持稳定以便将来接 SSE 加工。"""
    return obj


def _read_body_limit(rfile, headers, limit=2_000_000):
    """读请求体并限长。返回 bytes 或 None（超限时 None）。"""
    length = int(headers.get("Content-Length", 0) or 0)
    if length > limit:
        return None
    return rfile.read(length) if length > 0 else b""


def _engine_json_from(text):
    """从工具结果文本里提取 engine 返回（特征：JSON 顶层含 界面 键）。非则 None。"""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if "界面" not in text:
        return None
    try:
        d = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) and "界面" in d else None


def _harvest_engine_state(agent):
    """从会话消息倒序找最后一条 engine 返回；兼容直接结果与旧 Bash stdout。"""
    for m in reversed(agent.session.messages):
        if m.get("role") != "tool":
            continue
        try:
            outer = json.loads(m.get("content") or "")
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(outer, dict) and "界面" in outer:
            return outer
        d = _engine_json_from(outer.get("stdout") if isinstance(outer, dict) else None)
        if d is not None:
            return d
    return None


def _call_engine_service(payload, method="go"):
    """经共享 Engine Service 调用 go/judge，返回 (dict|None, err|None)。"""
    if _engine_client is None:
        return None, "engine service 未初始化"
    try:
        return _jsonable(_engine_client.call_operation(method, payload)), None
    except EngineClientError as exc:
        return None, str(exc)


# ---------- agent 后端: 进程内 agent-lite，按 session_id 维护会话 ----------
_agents = {}        # sid -> Agent
_agent_locks = {}   # sid -> threading.Lock (同一会话串行执行)
_agents_lock = threading.Lock()


def _get_agent(sid):
    """按 session_id 取/建 Agent 实例及其执行锁。返回 (agent, lock, created)。"""
    with _agents_lock:
        if sid not in _agent_locks:
            _agent_locks[sid] = threading.Lock()
        lock = _agent_locks[sid]
        if sid not in _agents:
            if AGENT_DIR not in sys.path:
                sys.path.insert(0, AGENT_DIR)  # agent-lite 以 core 为顶层包
            from core import Agent
            registry = build_wuxia_registry(_engine_client, _tools_manifest, SKILL_DIR)
            _agents[sid] = Agent(
                tools=registry, skill_dirs=[SKILL_DIR], system_prompt=AGENT_SYS,
                skill_usage_note=WEB_SKILL_USAGE_NOTE)
            return _agents[sid], lock, True
        return _agents[sid], lock, False


class Handler(BaseHTTPRequestHandler):
    server_version = "WuxiaRPG/1.0"

    def log_message(self, fmt, *args):  # 简化日志
        print(f"[{self.command}] {self.path} {args[0] if args else ''}")

    # ---------- 静态资源 ----------
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            # 根路由按 config.json server.frontend 分流：new→React(/ui/react)，old/vanilla→原生前端(/ui/vanilla)
            if DEFAULT_FRONTEND == "old":
                self._serve_file(GAME_INDEX, "text/html; charset=utf-8")
            else:
                self._serve_ui("")
        elif self.path == "/game":
            # /game 历史入口，指向原生前端（/ui/vanilla/game）
            self._serve_file(GAME_INDEX, "text/html; charset=utf-8")
        elif self.path in ("/ui/vanilla", "/ui/vanilla/game", "/ui/vanilla/game.html"):
            self._serve_file(GAME_INDEX, "text/html; charset=utf-8")
        elif self.path in ("/ui/vanilla/classic", "/ui/vanilla/classic.html", "/ui/vanilla/index.html"):
            self._serve_file(CLASSIC_INDEX, "text/html; charset=utf-8")
        elif self.path in ("/ui/vanilla/static/explore-lab", "/ui/vanilla/static/explore-lab.html"):
            self._serve_lab("explore-lab.html", "/ui/vanilla/game")
        elif self.path in ("/ui/vanilla/static/fight-lab", "/ui/vanilla/static/fight-lab.html"):
            self._serve_lab("fight-lab.html", "/ui/vanilla/game")
        elif self.path.startswith("/ui/vanilla/static/"):
            self._serve_static(self.path[len("/ui/vanilla/static/"):])
        elif self.path == "/ui/react" or self.path.startswith("/ui/react/"):
            # /ui/react → React 构建产物 dist；lab 经 /ui/react/*-lab 托管
            if self.path in ("/ui/react/explore-lab", "/ui/react/explore-lab.html"):
                self._serve_lab("explore-lab.html", "/ui/react")
            elif self.path in ("/ui/react/fight-lab", "/ui/react/fight-lab.html"):
                self._serve_lab("fight-lab.html", "/ui/react")
            elif self.path == "/ui/react":
                self._serve_ui("")
            else:
                self._serve_ui(self.path[len("/ui/react/"):])
        elif self.path == "/api/health":
            self._json({"ok": True, "root": ROOT})
        elif self.path == "/api/presets":
            self._serve_presets()
        elif self.path.startswith("/api/preset/"):
            self._serve_preset(self.path[len("/api/preset/"):])
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/chat":
            self._handle_chat()
        elif self.path == "/api/engine":
            self._handle_engine()
        else:
            self._json({"error": "not found"}, 404)

    # ---------- 引擎直通（见 DESIGN.md；UI 控件调 go，judge 为 GM 内部用） ----------
    def _handle_engine(self):
        payload = self._read_json_body()
        if payload is None:
            return
        slot = payload.get("槽位")
        if slot is None:
            self._json({"error": "缺少 槽位"}, 400)
            return
        actions = payload.get("行为")
        if not isinstance(actions, list):
            self._json({"error": "缺少 行为（数组）"}, 400)
            return
        # method:judge 走 engine judge（战斗-推进/战斗-开始/战后处置等 GM 侧入口）；缺省 go
        method = payload.get("method", "go")
        if method not in ("go", "judge"):
            self._json({"error": "method 仅允许 go/judge"}, 400)
            return
        payload = {k: v for k, v in payload.items() if k != "method"}
        result, err = _call_engine_service(payload, method=method)
        if err:
            self._json({"error": err}, 500)
        else:
            self._json(result)

    # ---------- 聊天流式 ----------
    def _handle_chat(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body or "{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "invalid json"}, 400)
            return

        message = (data.get("message") or "").strip()
        sid = (data.get("session_id") or "").strip()
        if not message:
            self._json({"error": "message required"}, 400)
            return
        if not sid:
            sid = str(uuid.uuid4())
        create = not _is_known(sid)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # 流式响应无 Content-Length，必须靠连接关闭标记响应结束。
        # 切勿用 keep-alive，否则浏览器 reader.read() 永不结束 → 前端卡死。
        self.close_connection = True
        self.send_header("Connection", "close")
        self.end_headers()

        def send(event, payload):
            try:
                self.wfile.write(f"event: {event}\n".encode("utf-8"))
                self.wfile.write(b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return False
            return True

        send("session", {"session_id": sid, "created": create})
        if _is_llm_backend():
            self._run_agent(sid, message, send)
        else:
            self._run_claude(sid, message, create, send)

    def _read_json_body(self):
        try:
            raw = _read_body_limit(self.rfile, self.headers)
            if raw is None:
                self._json({"error": "请求体过大"}, 413)
                return None
            return json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "invalid json"}, 400)
            return None

    def _run_agent(self, sid, message, send):
        """agent-lite 后端: 复刻 Agent.run 主循环，途中推送工具徽标。

        每轮 step 后无 tool_calls 即为最终回复——agent 只回终稿，
        无需 claude 后端的过渡语拦截。
        """
        try:
            agent, lock, _ = _get_agent(sid)
        except Exception as e:  # noqa: BLE001
            send("error", {"message": f"agent 后端初始化失败: {e}"})
            send("done", {"error": True})
            return

        with lock:  # 同一会话串行，避免历史交错
            try:
                agent.session.add_user(message)
                for _ in range(agent.max_iterations):
                    msg = agent.step()
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function") or {}
                        send("tool", {"name": fn.get("name"), "arguments": fn.get("arguments") or ""})
                    if not msg.get("tool_calls"):
                        send("delta", {"text": msg.get("content") or ""})
                        st = _harvest_engine_state(agent)
                        if st is not None:
                            send("state", st)
                        send("done", {"error": False, "session_id": sid})
                        return
                send("delta", {"text": "(已达到最大工具调用轮数，请换个方式描述或拆分任务。)"})
                st = _harvest_engine_state(agent)
                if st is not None:
                    send("state", st)
                send("done", {"error": False, "session_id": sid})
            except Exception as e:  # noqa: BLE001
                send("error", {"message": f"agent 后端执行出错: {e}"})
                send("done", {"error": True})

    def _run_claude(self, sid, message, create, send):
        cmd = [
            CLAUDE_COMMAND, "-p", "--verbose",
            "--output-format", "stream-json",
            "--permission-mode", PERMISSION_MODE,
            "--append-system-prompt", APPEND_SYS,
        ]
        if create:
            cmd += ["--session-id", sid]
        else:
            cmd += ["--resume", sid]
        cmd += [message]

        try:
            proc = subprocess.Popen(
                cmd, cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
        except FileNotFoundError:
            send("error", {"message": f"找不到 {CLAUDE_COMMAND}，请确认 CLI 已安装"})
            send("done", {"error": True})
            return

        # 文本按 message.id 暂存不即推：同消息内其后跟 tool_use 的文本是过程说明，
        # 遇工具即丢弃（工具徽标照常发）；只有确认是消息最后一块文本才输出（下一条
        # 消息开始或本回合结束时结算）。
        pend_mid = None
        pend_text = []

        def flush():
            nonlocal pend_mid, pend_text
            if pend_text:
                send("delta", {"text": "".join(pend_text)})
            pend_mid = None
            pend_text = []

        def drop():
            nonlocal pend_text
            if pend_text:
                print(f"[filter] 拦截过渡语: {''.join(pend_text).strip()[:40]}")
            pend_text = []

        got_done = False
        last_engine = None  # 本回合最后一次 engine 调用的返回（收割自 tool_result 流）
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = obj.get("type")
            if t == "assistant":
                msg = obj.get("message", {})
                mid = msg.get("id") or obj.get("uuid")
                if mid != pend_mid:
                    flush()  # 上一条消息收尾，其末尾文本块确认输出
                    pend_mid = mid
                for c in msg.get("content", []):
                    ct = c.get("type")
                    if ct == "text":
                        pend_text.append(c.get("text", ""))
                    elif ct == "tool_use":
                        drop()  # 后跟工具的文本属过程说明，拦截
                        send("tool", {"name": c.get("name"),
                                       "arguments": json.dumps(c.get("input") or {}, ensure_ascii=False)})
            elif t == "user":
                # 工具结果事件：非脏字段提取，仅当内容恰为 engine JSON（含 界面 键）才记
                for c in (obj.get("message") or {}).get("content") or []:
                    if not isinstance(c, dict) or c.get("type") != "tool_result":
                        continue
                    ec = c.get("content")
                    if isinstance(ec, list):
                        ec = "".join(b.get("text", "") for b in ec if isinstance(b, dict))
                    d = _engine_json_from(ec)
                    if d is not None:
                        last_engine = d
            elif t == "result":
                flush()
                err = obj.get("subtype") != "success"
                if last_engine is not None:
                    send("state", last_engine)
                send("done", {
                    "error": err,
                    "session_id": obj.get("session_id"),
                    "result": obj.get("result") if err else None,
                })
                got_done = True
                break
        if not got_done:
            flush()
        proc.wait()
        err_tail = proc.stderr.read().strip() if proc.stderr else ""

        if not got_done:
            # 无 result 事件：进程异常或被分类器阻断
            msg = err_tail or f"claude 进程退出 (code={proc.returncode})，未产生结果"
            send("error", {"message": msg})
            send("done", {"error": True})
        elif create:
            _mark_known(sid)

    # ---------- 预设角色只读端点（测试页 explore-lab 用；不入主界面前路） ----------
    def _presets_dir(self):
        return os.path.join(SKILL_DIR, "assets", "data", "characters")

    def _serve_presets(self):
        """列全部预设角色（名称/阵营/性别/年龄）——读 index.json 定位各档。"""
        try:
            idx = json.load(open(os.path.join(self._presets_dir(), "index.json"),
                                 encoding="utf-8"))
            out = []
            for name, rel in idx.items():
                try:
                    d = json.load(open(os.path.join(self._presets_dir(), rel),
                                       encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                out.append({"名称": name, "阵营": d.get("阵营"),
                            "性别": d.get("性别"), "年龄": d.get("年龄")})
            self._json(out)
        except (OSError, ValueError) as e:
            self._json({"error": str(e)}, 500)

    def _serve_preset(self, name):
        """取某预设角色的完整 dict（克隆建档用）。只读；不改写不落盘。"""
        import urllib.parse
        name = urllib.parse.unquote(name)
        try:
            idx = json.load(open(os.path.join(self._presets_dir(), "index.json"),
                                 encoding="utf-8"))
        except (OSError, ValueError) as e:
            self._json({"error": str(e)}, 500)
            return
        rel = idx.get(name)
        if not rel:
            self._json({"error": f"未找到预设角色【{name}】"}, 404)
            return
        try:
            d = json.load(open(os.path.join(self._presets_dir(), rel),
                               encoding="utf-8"))
        except (OSError, ValueError) as e:
            self._json({"error": str(e)}, 500)
            return
        self._json(d)

    # ---------- 工具 ----------
    def _serve_lab(self, name, target):
        """托管 web/ui/vanilla/static 下的 lab 测试页，并把跳转目标注入为 target。
        lab 仍读取 ?to= 查询参数覆盖该默认值，保留灵活性。"""
        path = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(path):
            self._json({"error": f"lab 页面 {name} 不存在"}, 404)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError:
            self._json({"error": "lab 页面读取失败"}, 404)
            return
        # 将缺省跳转目标 /game 注入为 target：替换 TO 定义行
        html = html.replace(
            "new URLSearchParams(location.search).get('to')||'/game'",
            f"new URLSearchParams(location.search).get('to')||{target!r}",
        )
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_ui(self, rel=""):
        """托管 React 版前端构建产物 react/dist：/ui/react → index.html，/ui/react/assets/... → 文件。
        未构建时返回提示，引导执行 npm run build。"""
        if not os.path.isdir(UI_DIR):
            self._json({"error": "React 前端未构建，请在 web/ui/react 下执行 npm run build"}, 404)
            return
        rel = rel.split("?", 1)[0].lstrip("/")
        if rel == "":
            self._serve_file(os.path.join(UI_DIR, "index.html"), "text/html; charset=utf-8")
            return
        path = os.path.normpath(os.path.join(UI_DIR, rel))
        if not path.startswith(os.path.abspath(UI_DIR) + os.sep):
            self._json({"error": "forbidden"}, 403)
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in _STATIC_MIME:
            self._json({"error": "not found"}, 404)
            return
        self._serve_file(path, _STATIC_MIME[ext])

    def _serve_static(self, rel):
        """托管 static/ 下静态资源：白名单扩展名 + 归一化防目录穿越。"""
        rel = rel.split("?", 1)[0].lstrip("/")
        path = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not path.startswith(os.path.abspath(STATIC_DIR) + os.sep):
            self._json({"error": "forbidden"}, 403)
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in _STATIC_MIME:
            self._json({"error": "not found"}, 404)
            return
        self._serve_file(path, _STATIC_MIME[ext])

    def _serve_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._json({"error": "file not found"}, 404)

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    global _engine_client, _tools_manifest
    # Web 后端走结构化战斗结果（battle.py 据 WUXIA_RPG_RENDER_MODULE 决定输出文本战报还是结构化回合详情）
    os.environ.setdefault("WUXIA_RPG_RENDER_MODULE", "WEB_UI")
    _load_config()
    _resolve_backend_config()
    _resolve_engine_config()
    _resolve_paths()
    _load_state()
    _engine_client = EngineClient.connect(
        SKILL_DIR, service_url=ENGINE_SERVICE_URL,
        timeout_ms=ENGINE_TIMEOUT_MS, port=ENGINE_PORT)
    _tools_manifest = _engine_client.get_tools()
    # _load_config 打印的 [config] 行用的是刷新前的 BACKEND，此处补打真实后端以免误导
    print(f"[config] 实际后端: backend={BACKEND}")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    srv = None
    try:
        srv = ThreadingHTTPServer((host, port), Handler)
        print(f"武侠RPG Web 已启动: http://{host}:{port}")
        print(f"项目根目录: {ROOT}")
        print(f"Engine Service: {_engine_client.service_url}")
        print(f"LLM 后端: {BACKEND}  (config.json backend_mode 或 LLM_BACKEND 环境变量: llm|claude)")
        if _is_llm_backend():
            print(f"agent 模型服务: AGENT_API_BASE={os.environ.get('AGENT_API_BASE', '(未设置)')} "
                  f"AGENT_MODEL={os.environ.get('AGENT_MODEL', '(未设置)')}")
        else:
            print(f"claude 命令: {CLAUDE_COMMAND}  权限模式: {PERMISSION_MODE}  "
                  f"(config.json claude.command / permission_mode 或对应环境变量)")
        print("Ctrl+C 退出")
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        if srv is not None:
            srv.server_close()
        _engine_client.close()


if __name__ == "__main__":
    main()
