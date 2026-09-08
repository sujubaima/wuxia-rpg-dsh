#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键执行武侠RPG完整回归。"""
import compileall
import json
import os
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
ROOT = SCRIPTS.parent

OLD_HOOKS = re.compile(
    r"on_cast|on_dodge|on_attack_acc|on_attacked|on_modify_damage|on_hit|"
    r"insight_rate_bonus|broadcast_stage"
)


def validate_json():
    count = 0
    for path in (ROOT / "assets" / "data").rglob("*.json"):
        with path.open(encoding="utf-8") as file:
            json.load(file)
        count += 1
    return count


def find_old_hooks():
    found = []
    for suffix in ("*.py", "*.md"):
        for path in ROOT.rglob(suffix):
            if path.resolve() == Path(__file__).resolve():
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if OLD_HOOKS.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    return found


def main():
    print("== Python编译 ==")
    if not compileall.compile_dir(str(SCRIPTS), quiet=1):
        return 1
    print("通过")

    print("\n== unittest + E2E ==")
    sys.path.insert(0, str(HERE))
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        return 1

    print("\n== JSON数据 ==")
    count = validate_json()
    print(f"通过：{count}个文件")

    print("\n== 旧钩子检查 ==")
    found = find_old_hooks()
    if found:
        print("\n".join(found))
        return 1
    print("通过：0处残留")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
