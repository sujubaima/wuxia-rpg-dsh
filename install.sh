#!/usr/bin/env bash
# 武侠RPG DSH 插件一键安装器。
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$ROOT/dsh-plugin"
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
  "$PLUGIN_DIR/presets/wuxia.patch.yml" \
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

SKILL_TARGET="$PLUGIN_DIR/skills/wuxia-rpg"
SKILL_STAGE="$PLUGIN_DIR/skills/.wuxia-stage-$$"
PRESET_PATCH="$PLUGIN_DIR/presets/wuxia.patch.yml"

# 清理旧版目录式 Preset（dsh 0.1.7 起不再读取 $DSH_HOME/.agent-presets）
LEGACY_PRESET="$DSH_HOME_DIR/.agent-presets/wuxia"
LEGACY_MARKER=".wuxia-rpg-managed"
if [[ -d "$LEGACY_PRESET" ]]; then
  if [[ -f "$LEGACY_PRESET/$LEGACY_MARKER" ]]; then
    echo "==> 移除旧版目录式 Preset：$LEGACY_PRESET"
    rm -rf -- "$LEGACY_PRESET"
  else
    echo "警告：$LEGACY_PRESET 非本项目管理，保留不动（新版 DSH 不读取该目录）" >&2
  fi
fi

echo "==> [2/4] 同步 Skill 到插件包 skills/"
rm -rf -- "$SKILL_STAGE"
python3 - "$SKILL_SOURCE" "$SKILL_STAGE" <<'PY'
import shutil
import sys
from pathlib import Path

src, dst = map(Path, sys.argv[1:])
ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "tmp")
shutil.copytree(src, dst, ignore=ignore)
if not (dst / "SKILL.md").is_file():
    raise SystemExit("错误：Skill 源不完整，缺少 SKILL.md")
PY
rm -rf -- "$SKILL_TARGET"
mv -- "$SKILL_STAGE" "$SKILL_TARGET"

grep -q "resolve('wuxia-rpg-dsh/package.json')" "$PRESET_PATCH" \
  || { echo "错误：Preset 声明未使用 wuxia-rpg-dsh 链接定位 skills/" >&2; exit 1; }

echo "==> [3/4] 接入 DSH profile: $PROFILE"
DSH_HOME="$DSH_HOME_DIR" "${DSH_CMD[@]}" plugin --profile "$PROFILE" add "$PLUGIN_DIR"
DSH_HOME="$DSH_HOME_DIR" "${DSH_CMD[@]}" plugin --profile "$PROFILE" why wuxia-rpg-dsh >/dev/null

echo "==> [4/4] 校验安装结果"
[[ -f "$PRESET_PATCH" ]] || { echo "错误：Preset 声明缺失" >&2; exit 1; }
[[ -f "$SKILL_TARGET/SKILL.md" ]] || { echo "错误：Skill 同步失败" >&2; exit 1; }

echo
echo "安装完成："
echo "  DSH CLI  : $DSH_CMD_LABEL"
echo "  DSH Home : $DSH_HOME_DIR"
echo "  Profile  : $PROFILE"
echo "  Preset   : $PRESET_PATCH（声明式，随插件 bundle 加载）"
echo "  Plugin   : $PLUGIN_DIR"
echo
printf '启动 DSH：DSH_HOME=%q' "$DSH_HOME_DIR"
printf ' %q' "${DSH_CMD[@]}"
printf ' web\n'
echo "选择“武侠GM”新建会话，然后输入“开始游戏”。"
echo "若以后移动项目目录，请在新位置重新运行本脚本以刷新插件链接。"
