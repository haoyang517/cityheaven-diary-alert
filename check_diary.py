#!/usr/bin/env python3
"""Check all CityHeaven targets and email today's new diary posts."""

from __future__ import annotations

import email.message
import html
import json
import os
import re
import smtplib
from datetime import datetime
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
    today = datetime.now(JST).date()
    results = {}
    for target in TARGETS:
        timestamp, context = parse_latest(fetch_page(target["url"]))
        results[target["id"]] = {
            "name": target["name"], "url": target["url"],
            "timestamp": timestamp.isoformat(), "context": context[:180],
            "is_today": timestamp.date() == today,
        }
        print(f"{target['name']}: latest={timestamp.isoformat()}")
    return results


def send_email(body: str) -> None:
    required = ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "NOTIFY_FROM", "NOTIFY_TO"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("缺少 GitHub Secrets: " + ", ".join(missing))
    message = email.message.EmailMessage()
    message["Subject"] = "CityHeaven 写メ日記更新通知"
    message["From"] = os.environ["NOTIFY_FROM"]
    message["To"] = os.environ["NOTIFY_TO"]
    message.set_content("今天有新的写メ日記投稿。\n\n" + body + "\n")
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


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
        if item["is_today"] and item["timestamp"] != previous.get(target_id, {}).get("timestamp"):
            notifications.append(
                f"【{item['name']}】\n投稿時間：{item['timestamp']}\n"
                f"網址：{item['url']}\n頁面摘要：{item['context']}"
            )
    if notifications:
        send_email("\n\n".join(notifications))
        print(f"已寄出 {len(notifications)} 個目標的写メ日記更新通知。")
    else:
        print("沒有新的今日写メ日記投稿，不寄信。")
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
