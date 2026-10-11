#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI is required. Install the Google Cloud CLI and try again." >&2
  exit 1
fi

PROJECT_ID="my-crawler-project-510912"
REGION="asia-east1"
SERVICE="diary-schedule-monitor"

echo "Deploying the current source in $PROJECT_DIR to $PROJECT_ID/$SERVICE ($REGION)..."

gcloud run deploy "$SERVICE" \
  --source . \
  --function check \
  --base-image python312 \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "diary-monitor-runtime@${PROJECT_ID}.iam.gserviceaccount.com" \
  --no-allow-unauthenticated \
  --cpu 1 \
  --memory 512Mi \
  --min 0 \
  --max 1 \
  --concurrency 1 \
  --timeout 300 \
  --set-env-vars STATE_BACKEND=firestore,FIRESTORE_COLLECTION=monitor_targets \
  --set-secrets TELEGRAM_BOT_TOKEN=telegram-bot-token:1,TELEGRAM_CHAT_ID=telegram-chat-id:1
