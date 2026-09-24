#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Slot 的提交代目录与跨请求待提交工作区。"""

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import os
import secrets
import shutil
import tempfile
import threading

from common import dao as dq
from common.json_io import (
    JsonMissingError, JsonSchemaError, atomic_write_json, fsync_directory, fsync_tree, read_json,
)


_DEFAULT_SAVE_DIR = dq.SAVE_DIR


_VIEW = ContextVar("slot_view", default="active")
_TRIAL = ContextVar("slot_pending_trial", default=None)
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCAL = threading.local()
_GENERATIONS = ".generations"
_RUNTIME = ".runtime"
_ACTIVE = "active_generation.json"
_PENDING = "pending_generation.json"
_RESPONSE = "committed_response.json"
_PUBLISHED_FROM = "published_from.json"


class LegacyPendingTurnError(RuntimeError):
    """旧格式槽位曾执行 go，但尚未完成 judge；禁止自动迁移。"""


class PendingWorkspaceError(RuntimeError):
    """待提交工作区状态不满足请求。"""


def physical_slot_path(slot, save_dir=_DEFAULT_SAVE_DIR):
    """返回不经过代目录重定向的物理槽位目录。"""
    return os.path.join(os.fspath(save_dir), f"slot_{int(slot)}")


def _runtime(root):
    return os.path.join(root, _RUNTIME)


def _manifest(root, filename):
    return os.path.join(_runtime(root), filename)


def _generation(root, name):
    if not isinstance(name, str) or not name.startswith("g_") or not name[2:].isalnum():
        raise JsonSchemaError(root, "代目录标识无效")
    return os.path.join(root, _GENERATIONS, name)


def _pointer(root, filename):
    path = _manifest(root, filename)
    try:
        pointer = read_json(path, expected_type=dict)
    except JsonMissingError:
        return None
    name = pointer.get("generation")
    directory = _generation(root, name)
    if not os.path.isdir(directory):
        raise JsonSchemaError(path, "代目录不存在")
    return name


def _write_pointer(root, filename, name):
    _generation(root, name)
    os.makedirs(_runtime(root), exist_ok=True)
    fsync_directory(root)
    atomic_write_json(_manifest(root, filename), {"generation": name}, indent=2)


def _sync_generation(root, generation):
    fsync_tree(generation)
    fsync_directory(os.path.dirname(generation))
    fsync_directory(root)


def _new_generation(root):
    return _generation(root, "g_" + secrets.token_hex(12))


def _copy_into(source, destination):
    # 文件必须独立复制：待提交层写入、删除不得修改已提交层。
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(_GENERATIONS))


def current_view():
    """返回当前请求所使用的槽位视图。"""
    return _VIEW.get()


@contextmanager
def slot_view(view):
    """临时选择路径视图：active、pending 或 legacy（仅迁移/维护使用）。"""
    if view not in {"active", "pending", "legacy"}:
        raise ValueError(f"未知 slot 视图：{view}")
    token = _VIEW.set(view)
    try:
        yield
    finally:
        _VIEW.reset(token)


def slot_path(slot, save_dir=_DEFAULT_SAVE_DIR):
    """按当前视图返回槽位路径；未迁移的旧档仍位于物理目录。"""
    root = physical_slot_path(slot, save_dir)
    if int(slot) <= 0 or _VIEW.get() == "legacy":
        return root
    if _VIEW.get() == "pending":
        trial = _TRIAL.get()
        if trial is not None and trial.root == os.path.abspath(root):
            if _pointer(root, _ACTIVE) == trial.generation:
                raise PendingWorkspaceError(f"槽位 {slot} 的试算已发布")
            return _generation(root, trial.generation)
        name = _pointer(root, _PENDING)
        if name is None or _published_pending(root, name, _pointer(root, _ACTIVE)):
            raise PendingWorkspaceError(f"槽位 {slot} 没有待提交工作区")
        return _generation(root, name)
    name = _pointer(root, _ACTIVE)
    if name is None and _pointer(root, _PENDING) is not None:
        raise PendingWorkspaceError(f"槽位 {slot} 尚未发布，无法使用已提交视图")
    return _generation(root, name) if name else root


def active_exists(slot, save_dir=_DEFAULT_SAVE_DIR):
    """新建待提交槽位在发布前不参与对外可见的槽位列表。"""
    root = physical_slot_path(slot, save_dir)
    if not os.path.isdir(root):
        return False
    if _pointer(root, _ACTIVE) is not None:
        return True
    if _pointer(root, _PENDING) is not None:
        return False
    return os.path.isfile(os.path.join(root, "meta.json"))


@contextmanager
def slot_lock(slot, save_dir=_DEFAULT_SAVE_DIR, *, blocking=True):
    """进程间 flock + 同进程线程互斥；可在同一线程嵌套。"""
    root = physical_slot_path(slot, save_dir)
    key = os.path.abspath(root)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    if not lock.acquire(blocking=blocking):
        raise PendingWorkspaceError(f"槽位 {slot} 正被其他请求使用")
    depths = getattr(_LOCAL, "depths", None)
    if depths is None:
        depths = _LOCAL.depths = {}
    try:
        if key not in depths:
            lock_dir = os.path.join(os.fspath(save_dir), ".locks")
            os.makedirs(lock_dir, exist_ok=True)
            fd = os.open(os.path.join(lock_dir, f"slot_{int(slot)}.lock"),
                         os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BaseException:
                os.close(fd)
                raise
            depths[key] = [fd, 0]
        depths[key][1] += 1
        try:
            yield
        finally:
            depths[key][1] -= 1
            if not depths[key][1]:
                fd, _ = depths.pop(key)
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
    finally:
        lock.release()


def _migrate_legacy(root):
    active = _pointer(root, _ACTIVE)
    if active:
        return active
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    path = _manifest(root, "turn_state.json")
    try:
        legacy_state = read_json(path, expected_type=dict)
    except JsonMissingError:
        state = "READY"
    else:
        from store import turn_state
        state = turn_state._validate(path, legacy_state)["state"]
    if state != "READY":
        raise LegacyPendingTurnError(f"旧档尚待处理的回合状态：{state}；请先完成或人工处置，不自动迁移")
    generation = _new_generation(root)
    try:
        _copy_into(root, generation)
        _sync_generation(root, generation)
        _write_pointer(root, _ACTIVE, os.path.basename(generation))
    except BaseException:
        # atomic_write_json may raise after replace; never remove a referenced generation.
        if _pointer(root, _ACTIVE) != os.path.basename(generation):
            shutil.rmtree(generation, ignore_errors=True)
        raise
    return os.path.basename(generation)


def _published_pending(root, pending, active):
    """试算发布后遗留的旧 pending 指针：仅以已提交代内的持久标记判定。"""
    if active is None or pending is None or pending == active:
        return pending is not None and pending == active
    try:
        marker = read_json(_manifest(_generation(root, active), _PUBLISHED_FROM),
                           expected_type=dict)
    except JsonMissingError:
        return False
    return marker.get("generation") == pending


def pending_exists(slot, save_dir=_DEFAULT_SAVE_DIR):
    root = physical_slot_path(slot, save_dir)
    pending = _pointer(root, _PENDING)
    active = _pointer(root, _ACTIVE)
    return pending is not None and not _published_pending(root, pending, active)


def begin_new_pending(slot, save_dir=_DEFAULT_SAVE_DIR):
    """原子占用新槽位，仅生成待提交目录；publish 前无已提交版本。"""
    if not isinstance(slot, int) or isinstance(slot, bool) or slot <= 0:
        raise ValueError("创建角色 slot 必须是正整数")
    with slot_lock(slot, save_dir):
        root = physical_slot_path(slot, save_dir)
        if os.path.lexists(root):
            raise FileExistsError(root)
        prefix = f".slot_{slot}_building_"
        for entry in os.scandir(os.fspath(save_dir)):
            if entry.name.startswith(prefix) and entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
        staged = tempfile.mkdtemp(prefix=prefix, dir=os.fspath(save_dir))
        renamed = False
        try:
            os.mkdir(os.path.join(staged, _GENERATIONS))
            generation = _new_generation(staged)
            os.mkdir(generation)
            _sync_generation(staged, generation)
            _write_pointer(staged, _PENDING, os.path.basename(generation))
            os.rename(staged, root)
            renamed = True
            fsync_directory(os.fspath(save_dir))
            return _generation(root, os.path.basename(generation))
        except BaseException:
            shutil.rmtree(root if renamed else staged, ignore_errors=True)
            fsync_directory(os.fspath(save_dir))
            raise


def begin_pending(slot, save_dir=_DEFAULT_SAVE_DIR):
    """从已提交代目录克隆待提交目录，跨请求保持；重复调用不得覆盖已有工作。"""
    with slot_lock(slot, save_dir):
        root = physical_slot_path(slot, save_dir)
        active = _migrate_legacy(root)
        pending = _pointer(root, _PENDING)
        if _published_pending(root, pending, active):
            os.remove(_manifest(root, _PENDING))
            fsync_directory(_runtime(root))
            if pending != active:
                shutil.rmtree(_generation(root, pending))
                fsync_directory(os.path.join(root, _GENERATIONS))
        elif pending:
            raise PendingWorkspaceError(f"槽位 {slot} 已有待提交工作区")
        generation = _new_generation(root)
        try:
            _copy_into(_generation(root, active), generation)
            # 旧响应只在已提交代中有效，不得当作本轮结果。
            response = _manifest(generation, _RESPONSE)
            if os.path.isfile(response):
                os.remove(response)
            _sync_generation(root, generation)
            _write_pointer(root, _PENDING, os.path.basename(generation))
        except BaseException:
            # A pointer write can succeed before its final fsync raises.
            if _pointer(root, _PENDING) != os.path.basename(generation):
                shutil.rmtree(generation, ignore_errors=True)
            raise
        return generation


class _PendingTrial:
    def __init__(self, root, previous, generation):
        self.root = os.path.abspath(root)
        self.previous = previous
        self.generation = generation
        self.committed = False

    def commit(self):
        """授权当前 trial 在退出前发布；不会修改持久 pending 指针。"""
        self.committed = True


@contextmanager
def pending_trial(slot, save_dir=_DEFAULT_SAVE_DIR):
    """私有试算副本；崩溃前未发布时仍由原 pending 指针提供可重试状态。"""
    with slot_lock(slot, save_dir):
        root = physical_slot_path(slot, save_dir)
        previous = _pointer(root, _PENDING)
        if previous is None or _published_pending(root, previous, _pointer(root, _ACTIVE)):
            raise PendingWorkspaceError(f"槽位 {slot} 没有可试算的待提交工作区")
        generation = _new_generation(root)
        try:
            _copy_into(_generation(root, previous), generation)
            _sync_generation(root, generation)
        except BaseException:
            shutil.rmtree(generation, ignore_errors=True)
            raise
        trial = _PendingTrial(root, previous, os.path.basename(generation))
        token = _TRIAL.set(trial)
        try:
            with slot_view("pending"):
                yield trial
        finally:
            _TRIAL.reset(token)
            if _pointer(root, _ACTIVE) == trial.generation:
                # active 已切换；仅在旧 pending 指针完成清理后删除旧快照。
                if _pointer(root, _PENDING) is None:
                    shutil.rmtree(_generation(root, previous), ignore_errors=True)
            else:
                shutil.rmtree(generation, ignore_errors=True)
            fsync_directory(os.path.join(root, _GENERATIONS))


def publish_pending(slot, response, save_dir=_DEFAULT_SAVE_DIR):
    """先完整持久化响应，再单文件原子切换 active 指针。"""
    with slot_lock(slot, save_dir):
        root = physical_slot_path(slot, save_dir)
        previous = _pointer(root, _PENDING)
        if previous is None:
            raise PendingWorkspaceError(f"槽位 {slot} 没有待提交工作区")
        active = _pointer(root, _ACTIVE)
        if _published_pending(root, previous, active):
            raise PendingWorkspaceError("待提交目录已是当前提交版本")
        trial = _TRIAL.get()
        if trial is not None and trial.root == os.path.abspath(root):
            if not trial.committed or trial.previous != previous:
                raise PendingWorkspaceError("试算尚未提交或待提交版本已变化")
            pending = trial.generation
        else:
            pending = previous
        generation = _generation(root, pending)
        _sync_generation(root, generation)
        atomic_write_json(_manifest(generation, _RESPONSE), response, indent=2)
        if pending != previous:
            atomic_write_json(_manifest(generation, _PUBLISHED_FROM),
                              {"generation": previous}, indent=2)
        _sync_generation(root, generation)
        _write_pointer(root, _ACTIVE, pending)
        try:
            os.remove(_manifest(root, _PENDING))
            fsync_directory(_runtime(root))
        except OSError:
            # active 已提交，持久标记让遗留旧 pending 不被误判为新一轮工作区。
            pass
        return generation


def abort_pending(slot, save_dir=_DEFAULT_SAVE_DIR):
    """丢弃未提交目录；若上次发布后崩溃，仅清除已提交的旧指针。"""
    with slot_lock(slot, save_dir):
        root = physical_slot_path(slot, save_dir)
        pending = _pointer(root, _PENDING)
        if pending is None:
            return False
        active = _pointer(root, _ACTIVE)
        os.remove(_manifest(root, _PENDING))
        fsync_directory(_runtime(root))
        if pending != active:
            shutil.rmtree(_generation(root, pending))
        if active is None:
            # 新档从未发布：释放整个占位，不能把空目录当作已建档。
            shutil.rmtree(root)
            fsync_directory(os.fspath(save_dir))
        else:
            fsync_directory(os.path.join(root, _GENERATIONS))
        return True


def read_committed_response(slot, save_dir=_DEFAULT_SAVE_DIR):
    """只从最新已提交代目录读取完整响应；未记录时返回 None。"""
    root = physical_slot_path(slot, save_dir)
    active = _pointer(root, _ACTIVE)
    if active is None:
        return None
    try:
        return read_json(_manifest(_generation(root, active), _RESPONSE), expected_type=dict)
    except JsonMissingError:
        return None
