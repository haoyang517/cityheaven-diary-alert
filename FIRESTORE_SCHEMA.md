# Firestore schema

This file is the schema contract for the diary and work-schedule monitor.
Firestore is schemaless and has no SQL `CREATE TABLE` DDL. This document
defines the equivalent collection, document, field types, and invariants used
by the application.

## Database

| Property | Value |
| --- | --- |
| Project | `my-crawler-project-510912` |
| Database ID | `(default)` |
| Location | `asia-east1` |
| Mode | Firestore Native |
| Edition | Standard |
| Free tier | Enabled (`freeTier: true`) |
| Delete protection | Disabled |
| Point-in-time recovery | Disabled |
| Collection | `monitor_targets` |

The default database was created on 2026-10-08 (Taipei time). Firestore creates
the collection and document when the application first writes them; no
separate table/collection creation step is needed. `FirestoreStateStore` uses the
default database and collection `monitor_targets` unless overridden by the
`FIRESTORE_COLLECTION` environment variable.

The first successful monitor invocation on 2026-10-08 created the baseline
document for the current target in `monitor_targets`.

## Collection and document structure

One document represents one monitored person/source pair. The document ID is
the target's stable `id` from `targets.py`; for the current target it is
`roses-girl-63866136`.

```text
monitor_targets/{target_id}
```

Each document has this shape:

```json
{
  "availability": "available",
  "diary": {
    "key": "<sha256 hex string>",
    "timestamp": "2026-10-08T12:34:00+09:00",
    "title": "<latest diary title from the profile page>"
  },
  "diary_source_id": "cityheaven-girlprofile-diary-v1",
  "schedule_source_id": "cityheaven-girlprofile-sukkin-v1",
  "schedule": {
    "2026-10-08": "12:00〜18:00",
    "2026-10-09": null
  }
}
```

| Field path | Firestore type | Meaning |
| --- | --- | --- |
| `availability` | String | `available` when the profile is readable, `unavailable` after a recognized missing-page response |
| `diary` | Map | Latest observed diary entry |
| `diary.key` | String | SHA-256 fingerprint of its timestamp and title; used to detect a changed latest entry |
| `diary.timestamp` | String | ISO 8601 timestamp with Japan time-zone offset |
| `diary.title` | String | Latest diary title shown on the CityHeaven profile page |
| `diary_source_id` | String | Diary parser/fingerprint identifier used to distinguish snapshots from different parser versions |
| `schedule_source_id` | String | Schedule parser/source identifier used to distinguish snapshots from different sources |
| `schedule` | Map | Effective schedule indexed by ISO date (`YYYY-MM-DD`) |
| `schedule.{date}` | String or null | Shift hours as displayed by the source; `null` means no shift on that date |

Schedule values are compared by date between polling runs. A new shift,
changed hours, or cancellation (`hours` to `null`) is an alert. A date missing
from a rolling schedule page is not treated as a cancellation. Past dates are
ignored for change notifications.

## Write and notification behavior

- On the first run, the monitor sends an initial setup message and saves the
  current diary and schedule as its baseline.
- Later runs notify on a changed diary fingerprint only when its timestamp is
  within the previous two hours. Schedule changes are notified independently.
- When the schedule source identifier changes, the current schedule becomes a
  new baseline without generating schedule alerts. Later polls compare against
  that baseline normally.
- When the diary parser identifier changes, a changed fingerprint with the
  same posting time is treated as a parser change. A different posting time can
  still trigger the normal two-hour alert.
- A visible `ページがありません` response or HTTP 404 triggers one
  unavailable-page alert, including when there is no prior snapshot. Repeated
  unavailable polls do not repeat the alert. When the page returns, the monitor
  sends one recovery alert and establishes a fresh diary/schedule baseline.
- Unchanged state is not written again.
- State is saved only after Telegram delivery succeeds, so a failed send can
  be retried on the next scheduled run. Telegram delivery and the Firestore
  write are not atomic; if Telegram accepts a message but the subsequent
  Firestore write fails, a retry can send the same alert again.
- The Cloud Run service uses the Google Cloud Firestore client library and its
  runtime service account. Grant that account `roles/datastore.user`; do not
  put service-account keys in the repository.

The application reads and writes documents directly by ID. It does not run
collection queries, so no custom composite index is currently required.

When a profile is unavailable, the document is reduced to:

```json
{
  "availability": "unavailable"
}
```
