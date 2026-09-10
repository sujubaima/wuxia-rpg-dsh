"""Web 会话与 HTTP 请求资源限制。"""

import json
import socket
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


class RequestLimitError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class SessionCapacityError(Exception):
    pass


class SessionBusyError(Exception):
    pass


def _exceeds_json_depth(value, max_depth):
    if not isinstance(value, (dict, list)):
        return False
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            return True
        values = current.values() if isinstance(current, dict) else current
        stack.extend(
            (item, depth + 1)
            for item in values
            if isinstance(item, (dict, list))
        )
    return False


def read_json_object(rfile, headers, connection, *, max_bytes, max_depth,
                     timeout_seconds):
    """按统一限制读取 UTF-8 JSON 对象。"""
    raw_length = headers.get("Content-Length")
    if raw_length is None:
        raise RequestLimitError(411, "缺少 Content-Length")
    try:
        length = int(raw_length)
    except (TypeError, ValueError) as exc:
        raise RequestLimitError(400, "Content-Length 无效") from exc
    if length < 0:
        raise RequestLimitError(400, "Content-Length 无效")
    if length > max_bytes:
        raise RequestLimitError(413, "请求体过大")

    old_timeout = connection.gettimeout()
    try:
        connection.settimeout(timeout_seconds)
        try:
            raw = rfile.read(length) if length else b""
        except socket.timeout as exc:
            raise RequestLimitError(408, "请求体读取超时") from exc
    finally:
        connection.settimeout(old_timeout)
    if len(raw) != length:
        raise RequestLimitError(400, "请求体不完整")

    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except UnicodeDecodeError as exc:
        raise RequestLimitError(400, "请求体必须为 UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise RequestLimitError(400, "invalid json") from exc
    except RecursionError as exc:
        raise RequestLimitError(400, "JSON 嵌套过深") from exc
    if not isinstance(data, dict):
        raise RequestLimitError(400, "请求体必须为 JSON 对象")
    if _exceeds_json_depth(data, max_depth):
        raise RequestLimitError(400, "JSON 嵌套过深")
    return data


class SlidingWindowLimiter:
    def __init__(self, period_seconds=60, clock=time.monotonic):
        self.period_seconds = period_seconds
        self.clock = clock
        self._events = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key, limit, now=None):
        if limit <= 0:
            return True
        current = self.clock() if now is None else now
        cutoff = current - self.period_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(current)
            return True

    def cleanup(self, now=None):
        current = self.clock() if now is None else now
        cutoff = current - self.period_seconds
        with self._lock:
            stale = []
            for key, events in self._events.items():
                while events and events[0] <= cutoff:
                    events.popleft()
                if not events:
                    stale.append(key)
            for key in stale:
                del self._events[key]
            return len(stale)


@dataclass
class _SessionEntry:
    value: object
    lock: threading.Lock
    last_used: float


class AgentSessionPool:
    def __init__(self, max_sessions, ttl_seconds, clock=time.monotonic):
        self.max_sessions = max(1, int(max_sessions))
        self.ttl_seconds = max(0, float(ttl_seconds))
        self.clock = clock
        self._entries = {}
        self._lock = threading.Lock()

    def _cleanup_locked(self, now):
        if self.ttl_seconds <= 0:
            return 0
        expired = [
            key for key, entry in self._entries.items()
            if not entry.lock.locked() and now - entry.last_used >= self.ttl_seconds
        ]
        for key in expired:
            del self._entries[key]
        return len(expired)

    def cleanup(self, now=None):
        current = self.clock() if now is None else now
        with self._lock:
            return self._cleanup_locked(current)

    def exists(self, key, now=None):
        current = self.clock() if now is None else now
        with self._lock:
            self._cleanup_locked(current)
            return key in self._entries

    def checkout(self, key, factory, now=None):
        current = self.clock() if now is None else now
        with self._lock:
            self._cleanup_locked(current)
            entry = self._entries.get(key)
            created = False
            if entry is None:
                oldest = None
                if len(self._entries) >= self.max_sessions:
                    candidates = [
                        (item.last_used, item_key)
                        for item_key, item in self._entries.items()
                        if not item.lock.locked()
                    ]
                    if not candidates:
                        raise SessionCapacityError("会话数量已达上限")
                    _, oldest = min(candidates)
                value = factory()
                if oldest is not None:
                    del self._entries[oldest]
                entry = _SessionEntry(value, threading.Lock(), current)
                self._entries[key] = entry
                created = True
            if not entry.lock.acquire(blocking=False):
                raise SessionBusyError("会话正在处理上一条请求")
            entry.last_used = current
            return entry.value, created

    def release(self, key, now=None):
        current = self.clock() if now is None else now
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.last_used = current
            entry.lock.release()

    def close(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            if entry.lock.locked():
                raise SessionBusyError("会话正在处理请求，暂时无法关闭")
            del self._entries[key]
            return True

    def count(self):
        with self._lock:
            return len(self._entries)
