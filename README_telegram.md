## Telegram 測試通知

本機測試時，先設定以下環境變數：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`：填入你的 Telegram chat ID

測試方式一：在本機執行：

```bash
export TELEGRAM_BOT_TOKEN='你的 Bot Token'
export TELEGRAM_CHAT_ID='你的 chat ID'
uv run notify_telegram.py
```

正式環境的 Telegram 憑證由 GCP Secret Manager 提供，設定方式見 `GCP_DEPLOYMENT.md`。
