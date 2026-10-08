## Telegram 測試通知

先在 GitHub Repository Secrets 新增：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`：填入你的 Telegram chat ID

測試方式一：在本機執行：

```bash
export TELEGRAM_BOT_TOKEN='你的 Bot Token'
export TELEGRAM_CHAT_ID='你的 chat ID'
uv run notify_telegram.py
```

測試方式二：到 GitHub 的 **Actions → Test Telegram Notification → Run workflow** 手動執行。
