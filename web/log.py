"""武侠RPG Web 最小日志：按天落盘 web/logs/server-YYYYMMDD.log，线程安全。

只记排障所需：请求生命周期（chat-start/done）、agent 步进与工具返回耗时、
engine 调用、异常完整调用栈。内容截断防膨胀。
"""
import os
import threading
import time
import traceback

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_lock = threading.Lock()


def _path() -> str:
    return os.path.join(_LOG_DIR, f"server-{time.strftime('%Y%m%d')}.log")


def _write(text: str) -> None:
    with _lock:
        try:
            os.makedirs(_LOG_DIR, exist_ok=True)
            with open(_path(), "a", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError:
            pass


def log(event: str, **fields) -> None:
    """记一行事件；字段值截断到 400 字符。"""
    parts = [time.strftime("%H:%M:%S"), f"[{event}]"]
    for key, value in fields.items():
        parts.append(f"{key}={str(value)[:400]}")
    _write(" ".join(parts))


def log_exc(event: str, **fields) -> None:
    """记录事件并附完整调用栈（在 except 块中调用）。"""
    log(event, **fields)
    _write(traceback.format_exc())
