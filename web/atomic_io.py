"""Web 本地文件原子写入工具。"""

import json
import os
import tempfile


def atomic_write_text(path, text):
    """在目标同目录写临时文件，再原子替换目标。"""
    target = os.path.abspath(os.fspath(path))
    directory = os.path.dirname(target)
    prefix = f".{os.path.basename(target)}."
    fd, temporary = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path, value, ensure_ascii=False, indent=None):
    """序列化 JSON 后原子写入。"""
    text = json.dumps(value, ensure_ascii=ensure_ascii, indent=indent)
    atomic_write_text(path, text)
