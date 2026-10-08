#!/usr/bin/env python3
"""Poll configured diary and schedule sources and send Telegram alerts."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from targets import TARGETS

JST = ZoneInfo("Asia/Tokyo")
STATE_FILE = Path(".cityheaven-state/state.json")
MISSING_PROFILE_MARKER = "ページがありません"
WEEKDAYS = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
    "月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6,
}


class PageTextParser(HTMLParser):
    """Collect visible text for recognizing a CityHeaven missing-page response."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def is_missing_profile_page(html_text: str) -> bool:
    parser = PageTextParser()
    parser.feed(html_text)
    visible_text = re.sub(r"\s+", " ", " ".join(parser.parts))
    return MISSING_PROFILE_MARKER in visible_text


class CityHeavenScheduleParser(HTMLParser):
    """Read the server-rendered girlprofile_sukkin schedule section."""

    def __init__(self) -> None:
        super().__init__()
        self.section_depth = 0
        self.row: dict[str, str] | None = None
        self.active_field: str | None = None
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if tag == "div" and not self.section_depth and attr.get("id") == "girlprofile_sukkin":
            self.section_depth = 1
        elif self.section_depth and tag == "div":
            self.section_depth += 1
        elif self.section_depth and tag == "li":
            self.row = {}
        elif self.section_depth and self.row is not None and tag in {"dt", "dd"}:
            self.active_field = "day" if tag == "dt" else "time"
            if tag == "dd" and "holiday2" in classes:
                self.row["holiday"] = "1"
        elif self.section_depth and self.active_field and tag == "br":
            self.row[self.active_field] = self.row.get(self.active_field, "") + " "

    def handle_data(self, data: str) -> None:
        if self.row is not None and self.active_field:
            self.row[self.active_field] = self.row.get(self.active_field, "") + data

    def handle_endtag(self, tag: str) -> None:
        if not self.section_depth:
            return
        if tag in {"dt", "dd"}:
            self.active_field = None
        elif tag == "li" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "div":
            self.section_depth -= 1


class CityHeavenDiaryParser(HTMLParser):
    """Read diary titles and timestamps shown on the girl profile page."""

    def __init__(self) -> None:
        super().__init__()
        self.section_depth = 0
        self.in_title = False
        self.row: dict[str, str] | None = None
        self.active_field: str | None = None
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if tag == "div" and not self.section_depth and attr.get("id") == "girlprofile_diary":
            self.section_depth = 1
        elif self.section_depth and tag == "div":
            self.section_depth += 1
            if "ttl" in classes:
                self.in_title = True
        elif self.section_depth and tag == "li":
            self.row = {}
        elif self.section_depth and self.row is not None and tag == "a" and self.in_title:
            self.active_field = "title"
        elif self.section_depth and self.row is not None and tag == "span" and "time" in classes:
            self.active_field = "time"

    def handle_data(self, data: str) -> None:
        if self.row is not None and self.active_field:
            self.row[self.active_field] = self.row.get(self.active_field, "") + data

    def handle_endtag(self, tag: str) -> None:
        if not self.section_depth:
            return
        if tag in {"a", "span"}:
            self.active_field = None
        elif tag == "li" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "div":
            self.in_title = False
            self.section_depth -= 1


def fetch_page(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CityHeavenDiaryChecker/1.0)",
            "Accept-Language": "ja,en;q=0.8",
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")


def parse_latest(html_text: str, now: datetime | None = None) -> dict[str, Any]:
    parser = CityHeavenDiaryParser()
    parser.feed(html_text)
    now = now or datetime.now(JST)
    matches: list[tuple[datetime, str]] = []
    for row in parser.rows:
        title = re.sub(r"\s+", " ", row.get("title", "")).strip()
        time_text = re.sub(r"\s+", " ", row.get("time", "")).strip()
        match = re.fullmatch(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})", time_text)
        if not title or not match:
            continue
        try:
            timestamp = datetime(
                now.year,
                int(match.group("month")),
                int(match.group("day")),
                int(match.group("hour")),
                int(match.group("minute")),
                tzinfo=JST,
            )
        except ValueError:
            continue
        if timestamp > now + timedelta(days=1):
            timestamp = timestamp.replace(year=timestamp.year - 1)
        matches.append((timestamp, title))
    if not matches:
        raise RuntimeError("找不到 CityHeaven 個人頁上的日記標題與時間，網站 HTML 可能已改版")
    timestamp, title = max(matches, key=lambda item: item[0])
    key = hashlib.sha256(f"{timestamp.isoformat()}|{title}".encode("utf-8")).hexdigest()
    return {"key": key, "timestamp": timestamp.isoformat(), "title": title[:180]}


def _schedule_date(day_text: str, weekday_text: str, today: date) -> date:
    match = re.fullmatch(r"\s*(\d{1,2})[./月-](\d{1,2})\s*", day_text)
    if not match:
        raise ValueError(f"無法解析班表日期：{day_text!r}")
    month, day = map(int, match.groups())
    weekday_value = weekday_text.strip()
    weekday = WEEKDAYS.get(weekday_value[:3].upper(), WEEKDAYS.get(weekday_value[:1]))
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if weekday is None or candidate.weekday() == weekday:
            candidates.append(candidate)
    if not candidates:
        raise ValueError(f"班表日期和星期不一致：{day_text} {weekday_text}")
    return min(candidates, key=lambda item: abs((item - today).days))


def parse_schedule(html_text: str, today: date | None = None) -> dict[str, str | None]:
    parser = CityHeavenScheduleParser()
    parser.feed(html_text)
    if not parser.rows:
        raise RuntimeError("找不到 CityHeaven #girlprofile_sukkin 班表，網站 HTML 可能已改版")
    today = today or datetime.now(JST).date()
    schedule: dict[str, str | None] = {}
    for row in parser.rows:
        day_text = re.sub(r"\s+", "", row.get("day", ""))
        if not day_text:
            raise RuntimeError(f"班表列缺少日期：{row}")
        match = re.fullmatch(r"(\d{1,2})[./月-](\d{1,2})(?:\((.)\))?", day_text)
        if not match:
            raise RuntimeError(f"無法解析 CityHeaven 班表日期：{day_text!r}")
        month, day, weekday = match.groups()
        shift_date = _schedule_date(f"{month}/{day}", weekday or "", today)
        if row.get("holiday"):
            shift = None
        else:
            times = re.findall(r"\d{1,2}:\d{2}", row.get("time", ""))
            if len(times) < 2:
                raise RuntimeError(f"班表列缺少出勤時間：{row}")
            shift = f"{times[0]}-{times[1]}"
        schedule[shift_date.isoformat()] = shift
    return schedule


def compare_schedules(
    previous: dict[str, str | None],
    current: dict[str, str | None],
    today: date,
) -> list[dict[str, str | None]]:
    changes = []
    for day in sorted(current):
        if date.fromisoformat(day) < today:
            continue
        old, new = previous.get(day), current[day]
        if old == new:
            continue
        if old is None and new is None:
            continue
        changes.append({"date": day, "old": old, "new": new})
    # Dates absent from a rolling week table are not treated as cancellations.
    return changes


def format_schedule_change(change: dict[str, str | None]) -> str:
    day = date.fromisoformat(change["date"] or "")
    old, new = change["old"], change["new"]
    if old is None:
        detail = f"新增出勤：{new}"
    elif new is None:
        detail = f"取消出勤：{old} → —"
    else:
        detail = f"時間變更：{old} → {new}"
    return f"【班表】{day:%m/%d} {detail}"


class JsonStateStore:
    """Local development state store. GCP uses FirestoreStateStore."""

    def __init__(self, path: Path = STATE_FILE) -> None:
        self.path = path
        self._states: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._states is None:
            self._states = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        return self._states

    def get(self, target_id: str) -> dict[str, Any] | None:
        return self._load().get(target_id)

    def save(self, target_id: str, state: dict[str, Any]) -> None:
        self._load()[target_id] = state
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._states, ensure_ascii=False, indent=2), encoding="utf-8")


class FirestoreStateStore:
    def __init__(self, collection: str = "monitor_targets") -> None:
        from google.cloud import firestore

        self.client = firestore.Client()
        self.collection = self.client.collection(collection)

    def get(self, target_id: str) -> dict[str, Any] | None:
        snapshot = self.collection.document(target_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def save(self, target_id: str, state: dict[str, Any]) -> None:
        self.collection.document(target_id).set(state)


def state_store() -> JsonStateStore | FirestoreStateStore:
    backend = os.environ.get("STATE_BACKEND", "firestore" if os.environ.get("K_SERVICE") else "json")
    if backend == "firestore":
        return FirestoreStateStore(os.environ.get("FIRESTORE_COLLECTION", "monitor_targets"))
    if backend == "json":
        return JsonStateStore()
    raise ValueError(f"不支援的 STATE_BACKEND：{backend}")


def send_telegram(body: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    missing = [name for name, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id)) if not value]
    if missing:
        raise RuntimeError("缺少環境設定：" + ", ".join(missing))
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urlencode({"chat_id": chat_id, "text": body}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API 回傳錯誤：{result}")


def _initial_message(target: dict[str, str], state: dict[str, Any], today: date) -> str:
    upcoming = [
        f"{date.fromisoformat(day):%m/%d} {shift}"
        for day, shift in sorted(state["schedule"].items())
        if shift and date.fromisoformat(day) >= today
    ]
    schedule_text = "\n".join(upcoming) if upcoming else "未來班表目前沒有列出出勤時間。"
    return (
        f"【{target['name']}】\n\n"
        f"■ 目前班表\n{schedule_text}\n"
        f"來源：{target['profile_url']}"
    )


def _missing_profile_message(target: dict[str, str]) -> str:
    return (
        f"【{target['name']}】\n\n"
        "■ 個人頁無法取得\n"
        "CityHeaven 顯示「ページがありません」，可能是頁面已刪除或暫時無法使用。\n"
        f"來源：{target['profile_url']}"
    )


def _restored_profile_message(target: dict[str, str]) -> str:
    return (
        f"【{target['name']}】\n\n"
        "■ 個人頁已恢復\n"
        "已重新取得主頁，這次會更新日記與班表基準。\n"
        f"來源：{target['profile_url']}"
    )


def run_check(
    *,
    fetcher=fetch_page,
    notifier=send_telegram,
    store=None,
    now: datetime | None = None,
    targets: list[dict[str, str]] | None = None,
) -> list[str]:
    now = now or datetime.now(JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    today = now.astimezone(JST).date()
    store = store or state_store()
    targets = targets or TARGETS
    observations = []

    # Fetch each profile once, then parse both diary and schedule before sending
    # or updating state. A parse failure leaves the previous snapshot intact.
    for target in targets:
        previous = store.get(target["id"])
        try:
            profile_html = fetcher(target["profile_url"])
        except HTTPError as error:
            if error.code != 404:
                raise
            observations.append((target, "unavailable", None, None, previous))
            continue
        if is_missing_profile_page(profile_html):
            observations.append((target, "unavailable", None, None, previous))
            continue
        diary = parse_latest(profile_html, now=now)
        schedule = parse_schedule(profile_html, today=today)
        observations.append((target, "available", diary, schedule, previous))

    notifications: list[str] = []
    updates: list[tuple[str, dict[str, Any]]] = []
    for target, availability, diary, schedule, previous in observations:
        previous_availability = previous.get("availability", "available") if previous else None
        if availability == "unavailable":
            state = {"availability": "unavailable"}
            if previous_availability != "unavailable":
                notifications.append(_missing_profile_message(target))
            if state != previous:
                updates.append((target["id"], state))
            continue

        assert diary is not None and schedule is not None
        state = {
            "availability": "available",
            "diary": diary,
            "schedule": schedule,
            "diary_source_id": target["diary_source_id"],
            "schedule_source_id": target["schedule_source_id"],
        }
        if previous_availability == "unavailable":
            notifications.append(_restored_profile_message(target))
            updates.append((target["id"], state))
            continue
        if previous is None:
            notifications.append(_initial_message(target, state, today))
            updates.append((target["id"], state))
            continue

        previous_diary = previous.get("diary", {})
        sections: list[str] = []
        if diary["key"] != previous_diary.get("key"):
            timestamp = datetime.fromisoformat(diary["timestamp"])
            diary_source_changed = previous.get("diary_source_id") != target["diary_source_id"]
            same_post_time = diary["timestamp"] == previous_diary.get("timestamp")
            if diary_source_changed and same_post_time:
                logging.info(
                    "Diary parser changed for %s; saving the existing post as a new baseline.",
                    target["id"],
                )
            elif now - timedelta(hours=2) <= timestamp <= now:
                sections.append(
                    "■ 日記更新\n"
                    f"標題：{diary['title']}\n"
                    f"投稿時間：{timestamp.month}/{timestamp.day} {timestamp:%H:%M}"
                )

        previous_schedule = previous.get("schedule", {})
        schedule_source_changed = previous.get("schedule_source_id") != target["schedule_source_id"]
        if schedule_source_changed:
            logging.info(
                "Schedule source changed for %s; saving a new baseline without schedule alerts.",
                target["id"],
            )
            schedule_changes = []
        else:
            schedule_changes = compare_schedules(previous_schedule, schedule, today)
        if schedule_changes:
            changes_text = "\n".join(format_schedule_change(change).replace("【班表】", "") for change in schedule_changes)
            sections.append(
                "■ 班表更新\n"
                f"{changes_text}"
            )
        if sections:
            notifications.append(
                f"【{target['name']}】\n\n"
                + "\n\n".join(sections)
                + f"\n\n來源：{target['profile_url']}"
            )

        if state != previous:
            updates.append((target["id"], state))

    if notifications:
        notifier("\n\n".join(notifications))
        logging.info("Sent Telegram notification with %d update(s).", len(notifications))
    else:
        logging.info("No new diary or schedule updates.")

    # Commit state only after notification succeeds. If Telegram fails, the
    # next Scheduler invocation retries the same changes instead of losing them.
    for target_id, state in updates:
        store.save(target_id, state)
    return notifications


def main() -> int:
    run_check()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
