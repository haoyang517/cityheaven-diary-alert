#!/bin/zsh

set -euo pipefail

PROJECT_DIR="/Users/haoyang/Workspace/python/cityheaven-diary-alert"
ENV_FILE="$PROJECT_DIR/.env.local"

if [[ ! -f "$ENV_FILE" ]]; then
  print -u2 "Missing $ENV_FILE"
  exit 1
fi

cd "$PROJECT_DIR"
set -a
source "$ENV_FILE"
set +a

exec /opt/homebrew/bin/uv run check_diary.py
