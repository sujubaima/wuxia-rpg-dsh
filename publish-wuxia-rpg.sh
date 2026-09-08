#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ONESKILL="${ONESKILL:-$HOME/.oneskill-cli/bin/oneskill}"
SKILL_PATH="$ROOT/wuxia-rpg"
SKILL_ID="17805"
BRIEF="武侠世界沉浸式文字RPG，丰富江湖交互。"
DOC_FILE="$ROOT/wuxia-rpg-detail-doc.md"
SCOPE="hub"

[[ -x "$ONESKILL" ]] || { echo "oneskill CLI 未找到: $ONESKILL" >&2; exit 1; }
[[ -f "$DOC_FILE" ]] || { echo "详细描述文件未找到: $DOC_FILE" >&2; exit 1; }

DETAIL_DOC="$(cat "$DOC_FILE")"

"$ONESKILL" update \
  --skill-path "$SKILL_PATH" \
  --skill-id "$SKILL_ID" \
  --brief-desc "$BRIEF" \
  --detail-doc "$DETAIL_DOC" \
  --publish-scope "$SCOPE"
