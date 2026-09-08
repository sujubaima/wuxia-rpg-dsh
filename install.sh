#!/usr/bin/env bash
# 武侠RPG DSH 插件一键安装器。
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$ROOT/dsh-plugin"
PRESET_SOURCE="$ROOT/dsh-preset/wuxia"
SKILL_SOURCE="$ROOT/wuxia-rpg"
PROFILE="web"
DSH_HOME_INPUT="${DSH_HOME:-$HOME/.dsh}"
SKIP_BUILD=false

usage() {
  cat <<'EOF'
用法：
  ./install.sh [--profile NAME] [--dsh-home PATH] [--skip-build]

选项：
  --profile NAME    安装到指定 DSH profile（默认 web）
  --dsh-home PATH   指定 DSH Home（默认 $DSH_HOME 或 ~/.dsh）
  --skip-build      跳过源码构建，仅使用已有 dsh-plugin/lib
  -h, --help        显示帮助
EOF
}

while (($#)); do
  case "$1" in
    --profile)
      (($# >= 2)) || { echo "错误：--profile 缺少参数" >&2; exit 2; }
      PROFILE="$2"
      shift 2
      ;;
    --dsh-home)
      (($# >= 2)) || { echo "错误：--dsh-home 缺少参数" >&2; exit 2; }
      DSH_HOME_INPUT="$2"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf '错误：未知参数 %q\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "$PROFILE" && "$PROFILE" != */* ]] || { echo "错误：profile 名无效：$PROFILE" >&2; exit 2; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || { echo "错误：未找到命令 $1" >&2; exit 1; }
}

require_command python3
require_command pnpm

python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    raise SystemExit("错误：需要 Python 3.9 或更高版本")
PY

DSH_HOME_DIR="$(python3 - "$DSH_HOME_INPUT" <<'PY'
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
)"

DSH_LOCAL_BIN="$DSH_HOME_DIR/profiles/node_modules/@deepseek-ai/dsh/lib/bin.js"
if command -v dsh >/dev/null 2>&1; then
  DSH_CMD=(dsh)
  DSH_CMD_LABEL="dsh"
elif [[ -f "$DSH_LOCAL_BIN" ]]; then
  # DSH Home 内已有 CLI（开发安装或此前完整安装）时直接使用，
  # 避免走 npx 在内存中解析整棵 DSH 依赖树。
  require_command node
  DSH_CMD=(node "$DSH_LOCAL_BIN")
  DSH_CMD_LABEL="node $DSH_LOCAL_BIN"
elif command -v npx >/dev/null 2>&1; then
  # npm exec 需在内存中解析整棵 DSH 依赖树（约 200 个包），
  # Node 默认 ~2GB 堆上限会 OOM，放宽到 4GB。
  DSH_NPM_HEAP="${NODE_OPTIONS:+$NODE_OPTIONS }--max-old-space-size=4096"
  DSH_CMD=(env "NODE_OPTIONS=$DSH_NPM_HEAP" npx --yes @deepseek-ai/dsh)
  DSH_CMD_LABEL="npx --yes @deepseek-ai/dsh"
else
  echo "错误：未找到 dsh，$DSH_HOME_DIR 内也没有可用的 DSH CLI，且未找到 npx" >&2
  exit 1
fi

for path in \
  "$PLUGIN_DIR/package.json" \
  "$PRESET_SOURCE/agent.cordis.yml" \
  "$PRESET_SOURCE/preset.yml" \
  "$SKILL_SOURCE/SKILL.md" \
  "$SKILL_SOURCE/tools.json" \
  "$SKILL_SOURCE/scripts/engine_gateway.py" \
  "$SKILL_SOURCE/scripts/engine_service.py"; do
  [[ -f "$path" ]] || { echo "错误：项目内容不完整，缺少 $path" >&2; exit 1; }
done

if [[ "$SKIP_BUILD" == false && -d "$PLUGIN_DIR/src" ]]; then
  require_command node
  require_command npm
  node -e 'const [major] = process.versions.node.split(".").map(Number); if (major < 18) { console.error("错误：需要 Node.js 18 或更高版本"); process.exit(1) }'
  echo "==> [1/4] 构建 DSH 插件"
  (cd "$PLUGIN_DIR" && npm ci && rm -rf lib && npm run build)
else
  echo "==> [1/4] 使用预构建 DSH 插件"
fi

for path in \
  "$PLUGIN_DIR/lib/index.js" \
  "$PLUGIN_DIR/lib/client.js" \
  "$PLUGIN_DIR/lib/config.js"; do
  [[ -f "$path" ]] || { echo "错误：插件构建产物不完整，缺少 $path" >&2; exit 1; }
done

PRESET_PARENT="$DSH_HOME_DIR/.agent-presets"
PRESET_TARGET="$PRESET_PARENT/wuxia"
MARKER=".wuxia-rpg-managed"
STAGE="$PRESET_PARENT/.wuxia-stage-$$"
BACKUP="$PRESET_PARENT/.wuxia-backup-$$"
INSTALLED=false
SUCCESS=false

cleanup() {
  status=$?
  rm -rf -- "$STAGE"
  if [[ "$SUCCESS" == false && "$INSTALLED" == true ]]; then
    rm -rf -- "$PRESET_TARGET"
    if [[ -e "$BACKUP" ]]; then mv -- "$BACKUP" "$PRESET_TARGET"; fi
  else
    rm -rf -- "$BACKUP"
  fi
  exit "$status"
}
trap cleanup EXIT

if [[ -e "$PRESET_TARGET" && ! -f "$PRESET_TARGET/$MARKER" ]]; then
  echo "错误：$PRESET_TARGET 已存在且不是本项目管理的 Preset，未覆盖" >&2
  exit 1
fi

mkdir -p -- "$PRESET_PARENT"
rm -rf -- "$STAGE" "$BACKUP"

echo "==> [2/4] 组装 portable 武侠 Preset"
python3 - "$PRESET_SOURCE" "$SKILL_SOURCE" "$STAGE" "$MARKER" <<'PY'
import os
import shutil
import sys
from pathlib import Path

preset_source, skill_source, stage, marker = map(Path, sys.argv[1:])
ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "tmp")
shutil.copytree(preset_source, stage)
shutil.copytree(skill_source, stage / "skills" / "wuxia-rpg", ignore=ignore)
(stage / marker).write_text("managed by cc-game-dsh install.sh\n", encoding="utf-8")
composition = (stage / "agent.cordis.yml").read_text(encoding="utf-8")
if "new URL('skills/', baseUrl)" not in composition:
    raise SystemExit("错误：Preset 未使用 baseUrl 定位 skills/")
if not (stage / "skills" / "wuxia-rpg" / "SKILL.md").is_file():
    raise SystemExit("错误：Preset 内 Skill 不完整")
PY

if [[ -e "$PRESET_TARGET" ]]; then mv -- "$PRESET_TARGET" "$BACKUP"; fi
mv -- "$STAGE" "$PRESET_TARGET"
INSTALLED=true

echo "==> [3/4] 接入 DSH profile: $PROFILE"
DSH_HOME="$DSH_HOME_DIR" "${DSH_CMD[@]}" plugin --profile "$PROFILE" add "$PLUGIN_DIR"
DSH_HOME="$DSH_HOME_DIR" "${DSH_CMD[@]}" plugin --profile "$PROFILE" why wuxia-rpg-dsh >/dev/null

echo "==> [4/4] 校验安装结果"
[[ -f "$PRESET_TARGET/agent.cordis.yml" ]] || { echo "错误：Preset 安装失败" >&2; exit 1; }
[[ -f "$PRESET_TARGET/skills/wuxia-rpg/SKILL.md" ]] || { echo "错误：Skill 安装失败" >&2; exit 1; }

SUCCESS=true

echo
echo "安装完成："
echo "  DSH CLI  : $DSH_CMD_LABEL"
echo "  DSH Home : $DSH_HOME_DIR"
echo "  Profile  : $PROFILE"
echo "  Preset   : $PRESET_TARGET"
echo "  Plugin   : $PLUGIN_DIR"
echo
printf '启动 DSH：DSH_HOME=%q' "$DSH_HOME_DIR"
printf ' %q' "${DSH_CMD[@]}"
printf ' web\n'
echo "选择“武侠GM”新建会话，然后输入“开始游戏”。"
echo "若以后移动项目目录，请在新位置重新运行本脚本以刷新插件链接。"
