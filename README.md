# CityHeaven Diary Alert

GitHub Actions 每 30 分鐘檢查 `targets.py` 中的 CityHeaven 女生頁面；如果任一目標有新的今日写メ日記，就透過 SMTP 寄一封彙總通知信。

要新增監控目標，只要編輯 [targets.py](targets.py)，加入一筆新的設定：

```python
{
    "id": "another-girl-123",
    "name": "Another girl",
    "url": "https://www.cityheaven.net/...",
},
```

在 repository 的 **Settings → Secrets and variables → Actions** 新增：

- `SMTP_HOST`：例如 `smtp.gmail.com`
- `SMTP_PORT`：通常是 `587`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`：Gmail 請使用 App Password
- `NOTIFY_FROM`
- `NOTIFY_TO`

工作流程檔案：`.github/workflows/check-cityheaven-diary.yml`。也可以從 Actions 頁面用 `workflow_dispatch` 手動執行。
