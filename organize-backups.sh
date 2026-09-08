#!/usr/bin/env bash
# 将项目根目录中的历史备份和临时产物统一归档到 backup/。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$ROOT/backup"
APPLY=false

usage() {
  cat <<'EOF'
用法：
  ./organize-backups.sh          预览将要归档的内容（不移动文件）
  ./organize-backups.sh --apply  执行归档
  ./organize-backups.sh --help   显示帮助

归档范围：
  backup/history/   _backups、data.20260728
  backup/archives/  项目根目录下的 zip/tar/tar.gz/tgz
  backup/generated/ dist、tmp、pack、nohup.out、config.json.temp

脚本只移动文件，不删除、不覆盖同名目标，也不递归归档源码内的压缩资源。
EOF
}

while (($#)); do
  case "$1" in
    --apply)
      APPLY=true
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
  shift
done

required=(
  agent
  web
  wuxia-rpg
  dsh-plugin
  docs
  data.now
  save
  config.json
)

missing=()
for item in "${required[@]}"; do
  [[ -e "$ROOT/$item" ]] || missing+=("$item")
done

if ((${#missing[@]})); then
  printf '错误：项目核心内容不完整，停止整理：\n' >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

sources=()
target_dirs=()

add_candidate() {
  local source="$1"
  local target_dir="$2"
  [[ -e "$source" || -L "$source" ]] || return 0
  sources+=("$source")
  target_dirs+=("$target_dir")
}

add_candidate "$ROOT/_backups" "$BACKUP_DIR/history"
add_candidate "$ROOT/data.20260728" "$BACKUP_DIR/history"

add_candidate "$ROOT/dist" "$BACKUP_DIR/generated"
add_candidate "$ROOT/tmp" "$BACKUP_DIR/generated"
add_candidate "$ROOT/pack" "$BACKUP_DIR/generated"
add_candidate "$ROOT/nohup.out" "$BACKUP_DIR/generated"
add_candidate "$ROOT/config.json.temp" "$BACKUP_DIR/generated"

shopt -s nullglob
for archive in "$ROOT"/*.zip "$ROOT"/*.tar.gz "$ROOT"/*.tgz "$ROOT"/*.tar; do
  add_candidate "$archive" "$BACKUP_DIR/archives"
done
shopt -u nullglob

if ((${#sources[@]} == 0)); then
  printf '没有发现需要归档的内容。项目目录已经是整理状态。\n'
  exit 0
fi

conflicts=()
for i in "${!sources[@]}"; do
  target="${target_dirs[$i]}/$(basename "${sources[$i]}")"
  [[ ! -e "$target" && ! -L "$target" ]] || conflicts+=("$target")
done

if ((${#conflicts[@]})); then
  printf '错误：以下目标已经存在。为避免覆盖，本次未移动任何内容：\n' >&2
  printf '  - %s\n' "${conflicts[@]}" >&2
  exit 1
fi

if [[ "$APPLY" == false ]]; then
  printf '预览模式：将归档以下 %d 项：\n' "${#sources[@]}"
else
  printf '开始归档以下 %d 项：\n' "${#sources[@]}"
fi

for i in "${!sources[@]}"; do
  source="${sources[$i]}"
  target_dir="${target_dirs[$i]}"
  target="$target_dir/$(basename "$source")"
  printf '  %s -> %s\n' "${source#"$ROOT"/}" "${target#"$ROOT"/}"

  if [[ "$APPLY" == true ]]; then
    mkdir -p "$target_dir"
    mv -- "$source" "$target"
  fi
done

if [[ "$APPLY" == false ]]; then
  printf '\n当前仅预览，未移动任何内容。确认后执行：\n'
  printf '  %q --apply\n' "$ROOT/organize-backups.sh"
else
  printf '\n归档完成：共移动 %d 项到 %s\n' "${#sources[@]}" "$BACKUP_DIR"
  printf '已保留核心代码、文档、当前数据、存档和必要构建产物。\n'
fi
