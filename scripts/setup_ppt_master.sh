#!/usr/bin/env bash
# 克隆并固定 ppt-master 到 LawPRE 验证过的版本。
# 用法：scripts/setup_ppt_master.sh [目标目录，默认 ~/tools/ppt-master]
set -euo pipefail

PINNED_COMMIT="b4efe3ddf237a97a42880164759162f8e2412f2f"   # v6.7.0
REPO_URL="https://github.com/hugohe3/ppt-master.git"
TARGET="${1:-${PPT_MASTER_DIR:-$HOME/tools/ppt-master}}"

if [ ! -d "$TARGET/.git" ]; then
  mkdir -p "$(dirname "$TARGET")"
  git clone "$REPO_URL" "$TARGET"
fi

git -C "$TARGET" fetch --quiet origin "$PINNED_COMMIT" 2>/dev/null || git -C "$TARGET" fetch --quiet origin
git -C "$TARGET" checkout --quiet --detach "$PINNED_COMMIT"

echo "ppt-master 已固定到 $(git -C "$TARGET" rev-parse --short HEAD)：$TARGET"
echo "安装依赖（可选，PPTX 导出需要）：pip install -r $TARGET/skills/ppt-master/requirements.txt"
