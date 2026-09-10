#!/usr/bin/env python3
"""Check all CityHeaven targets and send today's new diary posts to Telegram."""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from targets import TARGETS

JST = ZoneInfo("Asia/Tokyo")
CURRENT_FILE = Path(".cityheaven-current.json")
STATE_FILE = Path(".cityheaven-state/state.json")
DATE_RE = re.compile(
    r"(?P<year>20\d{2})?[./年-]?\s*(?P<month>\d{1,2})[./月-](?P<day>\d{1,2})"
    r"(?:日)?\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})"
)


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            value = html.unescape(data).strip()
            if value:
                self.parts.append(value)


def fetch_page(url: str) -> str:
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; CityHeavenDiaryChecker/1.0)",
        "Accept-Language": "ja,en;q=0.8",
    })
    with urlopen(request, timeout=30) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")


def parse_latest(html_text: str) -> tuple[datetime, str]:
    parser = TextParser()
    parser.feed(html_text)
    text = " ".join(parser.parts)
    now = datetime.now(JST)
    matches = []
    for match in DATE_RE.finditer(text):
        try:
            timestamp = datetime(
                int(match.group("year") or now.year), int(match.group("month")),
                int(match.group("day")), int(match.group("hour")),
                int(match.group("minute")), tzinfo=JST,
            )
        except ValueError:
            continue
        if timestamp <= now:
            context = re.sub(r"\s+", " ", text[max(0, match.start() - 140):match.end() + 140]).strip()
            matches.append((timestamp, context))
    if not matches:
        raise RuntimeError("找不到写メ日記日期時間，網站 HTML 可能已改版")
    return max(matches, key=lambda item: item[0])


def inspect_targets() -> dict:
    now = datetime.now(JST)
    window_start = now - timedelta(hours=2)
    results = {}
    for target in TARGETS:
        timestamp, context = parse_latest(fetch_page(target["url"]))
        results[target["id"]] = {
            "name": target["name"], "url": target["url"],
            "timestamp": timestamp.isoformat(), "context": context[:180],
            "is_recent": window_start <= timestamp <= now,
        }
        print(f"{target['name']}: latest={timestamp.isoformat()}")
    return results


def send_telegram(body: str) -> None:
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("缺少 GitHub Secrets: " + ", ".join(missing))
    from urllib.parse import urlencode
    request = Request(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data=urlencode({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": "CityHeaven 写メ日記更新通知\n\n" + body}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API 回傳錯誤：{result}")


def main() -> int:
    current = inspect_targets()
    CURRENT_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    fingerprint = "|".join(f"{key}:{value['timestamp']}" for key, value in sorted(current.items()))
    if os.environ.get("INSPECT_ONLY") == "1":
        output_file = os.environ.get("GITHUB_OUTPUT")
        if output_file:
            with open(output_file, "a", encoding="utf-8") as output:
                output.write(f"fingerprint={fingerprint}\n")
        return 0

    previous = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    notifications = []
    for target_id, item in current.items():
        if item["is_recent"] and item["timestamp"] != previous.get(target_id, {}).get("timestamp"):
            notifications.append(
                f"【{item['name']}】\n投稿時間：{item['timestamp']}\n"
                f"網址：{item['url']}\n頁面摘要：{item['context']}"
            )
    if notifications:
        send_telegram("\n\n".join(notifications))
        print(f"已發送 {len(notifications)} 個目標的 Telegram 写メ日記更新通知。")
    else:
        print("沒有最近 2 小時內的新写メ日記投稿，不發送 Telegram 通知。")
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
