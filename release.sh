#!/usr/bin/env bash
# 将武侠RPG完整套件打成可分发 zip。
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PKG_NAME="wuxia-rpg-suite"
STAMP="$(date +%Y%m%d-%H%M%S)"
DIST="$ROOT/dist"
ZIP="$DIST/$PKG_NAME-$STAMP.zip"
mkdir -p -- "$DIST"
WORK_DIR="$(mktemp -d "$DIST/.wuxia-rpg-release.XXXXXX")"
STAGE="$WORK_DIR/$PKG_NAME"
BUILD_LOG="$WORK_DIR/build.log"

cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

command -v python3 >/dev/null 2>&1 || { echo "错误：未找到 python3" >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "错误：未找到 npm" >&2; exit 1; }

echo "==> [1/7] 安装并锁定 DSH 构建依赖"
if ! (cd "$ROOT/dsh-plugin" && npm ci) >"$BUILD_LOG" 2>&1; then
  echo "错误：DSH 插件依赖安装失败" >&2
  python3 - "$BUILD_LOG" <<'PY' >&2
from pathlib import Path
import sys
print(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
PY
  exit 1
fi

echo "==> [2/7] 构建并测试 DSH 插件"
if ! (cd "$ROOT/dsh-plugin" && npm run build && npm test) >"$BUILD_LOG" 2>&1; then
  echo "错误：DSH 插件构建或测试失败" >&2
  python3 - "$BUILD_LOG" <<'PY' >&2
from pathlib import Path
import sys
print(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
PY
  exit 1
fi

echo "==> [3/7] 安装依赖并构建 Web React"
if ! (cd "$ROOT/web/ui/react" && npm ci && npm run build) >"$BUILD_LOG" 2>&1; then
  echo "错误：Web React 依赖安装、类型检查或构建失败" >&2
  python3 - "$BUILD_LOG" <<'PY' >&2
from pathlib import Path
import sys
print(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
PY
  exit 1
fi

echo "==> [4/7] 校验基线数据完整性"
if ! python3 "$ROOT/wuxia-rpg/scripts/validate_data.py"; then
  echo "错误：基线数据完整性校验失败" >&2
  exit 1
fi

echo "==> [5/7] 组装发布目录"
python3 - "$ROOT" "$STAGE" <<'PY'
import shutil
import sys
from pathlib import Path

root, stage = map(Path, sys.argv[1:])

COMMON_IGNORES = {
    "__pycache__", "*.pyc", ".DS_Store", "node_modules", ".git",
    ".sessions.json", "save",
}

def ignore(directory, names):
    ignored = set()
    for name in names:
        if name in {"__pycache__", ".DS_Store", "node_modules", ".git", ".sessions.json"}:
            ignored.add(name)
        elif name.endswith(".pyc"):
            ignored.add(name)
    current = Path(directory)
    if current == root / "wuxia-rpg" / "scripts" and "tmp" in names:
        ignored.add("tmp")
    if current == root / "dsh-plugin":
        ignored.update({"src", "tests", "tsconfig.json", "build-client.mjs", "package-lock.json"} & set(names))
    if current == root / "web" / "ui" / "react" and "node_modules" in names:
        ignored.add("node_modules")
    return ignored

for name in ("wuxia-rpg", "web", "agent", "dsh-plugin", "dsh-preset", "docs"):
    source = root / name
    if source.exists():
        shutil.copytree(source, stage / name, ignore=ignore)

for name in ("config.json", "install.sh", "README.md"):
    shutil.copy2(root / name, stage / name)
PY

echo "==> [6/7] 校验发布包可移植性"
python3 - "$STAGE" "$ROOT" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
source_root = Path(sys.argv[2]).resolve()
need = [
    root / "install.sh",
    root / "dsh-plugin" / "lib" / "index.js",
    root / "dsh-plugin" / "lib" / "client.js",
    root / "dsh-preset" / "wuxia" / "agent.cordis.yml",
    root / "wuxia-rpg" / "SKILL.md",
    root / "wuxia-rpg" / "tools.json",
    root / "wuxia-rpg" / "scripts" / "engine_gateway.py",
    root / "wuxia-rpg" / "scripts" / "engine_service.py",
    root / "wuxia-rpg" / "scripts" / "validate_data.py",
    root / "web" / "ui" / "react" / "dist" / "index.html",
    root / "web" / "ui" / "react" / "dist" / "assets" / "index.js",
    root / "web" / "ui" / "react" / "dist" / "assets" / "index.css",
]
missing = [str(path.relative_to(root)) for path in need if not path.is_file()]
if missing:
    raise SystemExit("错误：发布包缺少 " + ", ".join(missing))

forbidden = (
    str(source_root),
    str(Path.home().resolve()),
    "DEFAULT_PROJECT_ROOT",
    "../../dsh/deepseek-harness/",
    "http://localhost:8011",
)
extensions = {".js", ".ts", ".tsx", ".mjs", ".py", ".sh", ".json", ".md", ".yml", ".yaml", ".d.ts"}
hits = []
for path in root.rglob("*"):
    if not path.is_file() or path.suffix.lower() not in extensions:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for needle in forbidden:
        if needle in text:
            hits.append(f"{path.relative_to(root)}: {needle}")
if hits:
    raise SystemExit("错误：发布包仍含本机依赖\n  " + "\n  ".join(hits))
PY

echo "==> [7/7] 生成 $ZIP"
python3 - "$STAGE" "$ZIP" "$PKG_NAME" <<'PY'
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

source = Path(sys.argv[1])
zip_path = Path(sys.argv[2])
package_name = Path(sys.argv[3])
with ZipFile(zip_path, "x", ZIP_DEFLATED) as archive:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            archive.write(path, package_name / path.relative_to(source))
PY

size="$(python3 - "$ZIP" <<'PY'
import os, sys
size = os.path.getsize(sys.argv[1])
for unit in ("B", "KiB", "MiB", "GiB"):
    if size < 1024 or unit == "GiB":
        print(f"{size:.1f} {unit}")
        break
    size /= 1024
PY
)"

echo
echo "完成：$ZIP ($size)"
echo "  自带 Web：python3 web/server.py"
echo "  DSH 插件：./install.sh"
