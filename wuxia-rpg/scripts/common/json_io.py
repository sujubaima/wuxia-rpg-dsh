#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON 分类读取与原子写入。"""

import json
import logging
import os
import tempfile


_LOGGER = logging.getLogger(__name__)


class JsonReadError(Exception):
    """可稳定识别的 JSON 文件读取错误。"""

    code = "json_read_error"

    def __init__(self, path, detail):
        self.path = os.path.abspath(os.fspath(path))
        self.detail = str(detail)
        super().__init__(f"JSON 文件读取失败：{self.path}（{self.detail}）")


class JsonMissingError(JsonReadError):
    code = "json_missing"


class JsonAccessError(JsonReadError):
    code = "json_io_error"


class JsonEncodingError(JsonReadError):
    code = "json_encoding_error"


class JsonSyntaxError(JsonReadError):
    code = "json_syntax_error"


class JsonSchemaError(JsonReadError):
    code = "json_schema_error"


def _type_name(expected_type):
    types = expected_type if isinstance(expected_type, tuple) else (expected_type,)
    return "/".join(t.__name__ for t in types)


def read_json(path, *, expected_type=None):
    """读取 UTF-8 JSON；按缺失、IO、编码、语法和顶层类型分类报错。"""
    target = os.path.abspath(os.fspath(path))
    try:
        with open(target, encoding="utf-8") as file:
            try:
                value = json.load(file)
            except UnicodeDecodeError as exc:
                raise JsonEncodingError(target, f"不是有效 UTF-8：{exc}") from exc
            except json.JSONDecodeError as exc:
                raise JsonSyntaxError(
                    target, f"JSON 语法错误（第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}"
                ) from exc
    except FileNotFoundError as exc:
        raise JsonMissingError(target, "文件不存在") from exc
    except JsonReadError:
        raise
    except OSError as exc:
        raise JsonAccessError(target, f"{exc.strerror or str(exc)}") from exc
    if expected_type is not None and not isinstance(value, expected_type):
        raise JsonSchemaError(
            target, f"顶层类型应为 {_type_name(expected_type)}，实际为 {type(value).__name__}"
        )
    return value


def warn_json_read(error):
    """记录允许降级的 JSON 读取错误，不污染 stdout 协议。"""
    _LOGGER.warning("JSON 读取降级 [%s] %s", error.code, error)


def atomic_write_json(path, value, *, ensure_ascii=False, indent=None):
    """将 JSON 写入同目录临时文件，落盘后原子替换目标。"""
    target = os.path.abspath(os.fspath(path))
    directory = os.path.dirname(target)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(target)}.", suffix=".tmp", dir=directory
    )
    try:
        file = os.fdopen(fd, "w", encoding="utf-8")
        fd = None
        with file:
            json.dump(value, file, ensure_ascii=ensure_ascii, indent=indent)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
