from datetime import datetime
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import unittest
from unittest.mock import patch

from check_diary import compare_schedules, is_missing_profile_page, parse_latest, parse_schedule, run_check
import main


JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=JST)
DIARY_HTML = """
<div id="girlprofile_diary"><ul id="new_data">
  <li><div class="inner"><div class="txt"><div class="ttl"><a href="/diary/pd-123">素敵な一日</a></div><div class="option"><span class="time">10/7 14:20</span></div></div></div></li>
</ul></div>
"""
SCHEDULE_HTML = """
<div id="girlprofile_sukkin"><ul id="girl_sukkin">
  <li><dl><dt>10/7(水)</dt><dd class="holiday2"></dd></dl></li>
  <li><dl><dt>10/8(木)</dt><dd class="holiday2"></dd></dl></li>
  <li><dl><dt>10/9(金)</dt><dd><div class="go2">14:00<br />-<br />18:00</div></dd></dl></li>
  <li><dl><dt>10/10(土)</dt><dd class="holiday2"></dd></dl></li>
  <li><dl><dt>10/11(日)</dt><dd class="holiday2"></dd></dl></li>
  <li><dl><dt>10/12(月)</dt><dd class="holiday2"></dd></dl></li>
  <li><dl><dt>10/13(火)</dt><dd class="holiday2"></dd></dl></li>
</ul></div>
"""


class MemoryStore:
    def __init__(self):
        self.states = {}
        self.writes = 0

    def get(self, target_id):
        return self.states.get(target_id)

    def save(self, target_id, state):
        self.states[target_id] = state
        self.writes += 1


class MonitorTests(unittest.TestCase):
    def test_http_entrypoint_requires_post_and_calls_monitor(self):
        self.assertEqual(main.check(type("Request", (), {"method": "GET"})()), ("Method Not Allowed", 405))
        request = type("Request", (), {"method": "POST"})()
        with patch.object(main, "run_check") as run:
            self.assertEqual(main.check(request), ("Monitor completed", 200))
            run.assert_called_once_with()

    def test_parse_schedule_dates_and_times(self):
        schedule = parse_schedule(SCHEDULE_HTML, today=NOW.date())
        self.assertEqual(len(schedule), 7)
        self.assertIsNone(schedule["2026-10-07"])
        self.assertEqual(schedule["2026-10-09"], "14:00-18:00")

    def test_parse_latest_diary_timestamp(self):
        post = parse_latest(DIARY_HTML, now=NOW)
        self.assertEqual(post["timestamp"], "2026-10-07T14:20:00+09:00")
        self.assertEqual(post["title"], "素敵な一日")
        self.assertTrue(post["key"])

    def test_missing_profile_marker_is_detected_from_visible_page_text(self):
        self.assertTrue(is_missing_profile_page("<nav>風俗情報シティヘブンネット</nav><main>ページがありません</main>"))
        self.assertFalse(is_missing_profile_page(DIARY_HTML + SCHEDULE_HTML))

    def test_schedule_diff_detects_new_changed_and_cancelled_shifts(self):
        previous = {"2026-10-08": None, "2026-10-09": "14:00-18:00", "2026-10-10": "12:00-16:00"}
        current = {"2026-10-08": "13:00-17:00", "2026-10-09": "15:00-18:00", "2026-10-10": None}
        changes = compare_schedules(previous, current, NOW.date())
        self.assertEqual(
            changes,
            [
                {"date": "2026-10-08", "old": None, "new": "13:00-17:00"},
                {"date": "2026-10-09", "old": "14:00-18:00", "new": "15:00-18:00"},
                {"date": "2026-10-10", "old": "12:00-16:00", "new": None},
            ],
        )

    def test_unchanged_poll_does_not_send_or_write_state(self):
        store = MemoryStore()
        messages = []
        pages = {"profile": DIARY_HTML + SCHEDULE_HTML}
        target = {
            "id": "yuki", "name": "水瀬ゆき", "profile_url": "profile",
            "diary_source_id": "cityheaven-diary-v1", "schedule_source_id": "cityheaven-schedule-v1",
        }
        fetch = lambda url: pages[url]

        run_check(fetcher=fetch, notifier=messages.append, store=store, now=NOW, targets=[target])
        self.assertEqual(len(messages), 1)  # First-run setup/test message.
        self.assertEqual(store.writes, 1)

        run_check(fetcher=fetch, notifier=messages.append, store=store, now=NOW, targets=[target])
        self.assertEqual(len(messages), 1)
        self.assertEqual(store.writes, 1)

    def test_cancelled_shift_sends_notification_and_updates_snapshot(self):
        store = MemoryStore()
        messages = []
        pages = {"profile": DIARY_HTML + SCHEDULE_HTML}
        target = {
            "id": "yuki", "name": "水瀬ゆき", "profile_url": "profile",
            "diary_source_id": "cityheaven-diary-v1", "schedule_source_id": "cityheaven-schedule-v1",
        }
        fetch = lambda url: pages[url]
        run_check(fetcher=fetch, notifier=messages.append, store=store, now=NOW, targets=[target])
        pages["profile"] = DIARY_HTML + SCHEDULE_HTML.replace(
            '<dd><div class="go2">14:00<br />-<br />18:00</div></dd>',
            '<dd class="holiday2"></dd>',
        )

        run_check(fetcher=fetch, notifier=messages.append, store=store, now=NOW, targets=[target])
        self.assertIn("取消出勤：14:00-18:00 → —", messages[-1])
        self.assertIsNone(store.states["yuki"]["schedule"]["2026-10-09"])

    def test_source_change_rebaselines_once_then_tracks_real_changes(self):
        store = MemoryStore()
        messages = []
        target = {
            "id": "yuki", "name": "水瀬ゆき", "profile_url": "profile",
            "diary_source_id": "cityheaven-diary-v1", "schedule_source_id": "cityheaven-schedule-v1",
        }
        store.states["yuki"] = {
            "diary": {
                "key": "legacy-context-fingerprint",
                "timestamp": parse_latest(DIARY_HTML, now=NOW)["timestamp"],
            },
            "schedule": {"2026-10-09": "12:00-18:00"},
        }
        fetch = lambda url: DIARY_HTML + SCHEDULE_HTML

        run_check(fetcher=fetch, notifier=messages.append, store=store, now=NOW, targets=[target])
        self.assertEqual(messages, [])
        self.assertEqual(store.states["yuki"]["schedule_source_id"], "cityheaven-schedule-v1")

        updated = SCHEDULE_HTML.replace("14:00<br />-<br />18:00", "15:00<br />-<br />19:00")
        run_check(
            fetcher=lambda url: DIARY_HTML + updated,
            notifier=messages.append,
            store=store,
            now=NOW,
            targets=[target],
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("時間變更：14:00-18:00 → 15:00-19:00", messages[0])

    def test_diary_and_schedule_updates_share_one_profile_source(self):
        store = MemoryStore()
        messages = []
        target = {
            "id": "yuki", "name": "水瀬ゆき", "profile_url": "profile",
            "diary_source_id": "cityheaven-diary-v1", "schedule_source_id": "cityheaven-schedule-v1",
        }
        store.states["yuki"] = {
            "diary": {"key": "older-fingerprint", "timestamp": "2026-10-07T14:00:00+09:00"},
            "schedule": {"2026-10-09": None},
            "diary_source_id": "cityheaven-diary-v1",
            "schedule_source_id": "cityheaven-schedule-v1",
        }

        run_check(
            fetcher=lambda url: DIARY_HTML + SCHEDULE_HTML,
            notifier=messages.append,
            store=store,
            now=NOW,
            targets=[target],
        )
        self.assertEqual(len(messages), 1)
        self.assertIn("■ 日記更新", messages[0])
        self.assertIn("■ 班表更新", messages[0])
        self.assertEqual(messages[0].count("來源：profile"), 1)

    def test_missing_profile_notifies_on_first_run_once_and_on_recovery(self):
        store = MemoryStore()
        messages = []
        pages = {"profile": "<nav>風俗情報シティヘブンネット</nav><main>ページがありません</main>"}
        target = {
            "id": "yuki", "name": "水瀬ゆき", "profile_url": "profile",
            "diary_source_id": "cityheaven-diary-v1", "schedule_source_id": "cityheaven-schedule-v1",
        }
        fetch = lambda url: pages[url]

        run_check(fetcher=fetch, notifier=messages.append, store=store, now=NOW, targets=[target])
        self.assertEqual(len(messages), 1)
        self.assertIn("個人頁無法取得", messages[0])
        self.assertEqual(store.states["yuki"], {"availability": "unavailable"})

        run_check(fetcher=fetch, notifier=messages.append, store=store, now=NOW, targets=[target])
        self.assertEqual(len(messages), 1)
        self.assertEqual(store.writes, 1)

        pages["profile"] = DIARY_HTML + SCHEDULE_HTML
        run_check(fetcher=fetch, notifier=messages.append, store=store, now=NOW, targets=[target])
        self.assertEqual(len(messages), 2)
        self.assertIn("個人頁已恢復", messages[-1])
        self.assertEqual(store.states["yuki"]["availability"], "available")

    def test_http_404_is_treated_as_unavailable_profile(self):
        store = MemoryStore()
        messages = []
        target = {
            "id": "yuki", "name": "水瀬ゆき", "profile_url": "profile",
            "diary_source_id": "cityheaven-diary-v1", "schedule_source_id": "cityheaven-schedule-v1",
        }

        def not_found(url):
            raise HTTPError(url, 404, "Not Found", None, None)

        run_check(fetcher=not_found, notifier=messages.append, store=store, now=NOW, targets=[target])
        self.assertEqual(len(messages), 1)
        self.assertEqual(store.states["yuki"]["availability"], "unavailable")


if __name__ == "__main__":
    unittest.main()
