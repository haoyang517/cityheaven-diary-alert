#!/usr/bin/env python3
"""Send a one-off Telegram test notification."""

from __future__ import annotations

import argparse
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def send_test_message(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("請設定 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")

    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urlencode({"chat_id": chat_id, "text": message}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API 回傳錯誤：{result}")
    print("Telegram 測試通知已發送。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--message",
        default="CityHeaven Diary Alert 測試通知成功！",
        help="要發送的測試訊息",
    )
    args = parser.parse_args()
    send_test_message(args.message)
