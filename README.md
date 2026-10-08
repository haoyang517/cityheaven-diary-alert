# Soup Schedule Alert

Python monitor for diary posts and work schedules. It runs on GCP every 30
minutes and sends combined Telegram notifications. The budget guard,
Firestore database, private Cloud Run monitor, and Cloud Scheduler job are
deployed.

## Current source

- Diary and schedule: the same CityHeaven girl profile configured in `targets.py`.
  Its server-rendered `#girlprofile_sukkin` section contains the attendance
  schedule, so each poll fetches the page once and parses both.

The parser is site-specific; another site's parser can be added later if more
monitored sites are configured.

## Notification behavior

- A newly observed diary post is sent only when its timestamp is within the
  last two hours. The notice contains its title, posting time, and CityHeaven
  profile URL. The profile URL appears once per person's message. Older posts
  advance the seen cursor without a notification.
- A schedule is compared by calendar date. New shifts, time changes, and
  cancellations are sent with the same profile URL. If diary and schedule
  updates occur for one person in the same poll, they are grouped under that
  person's name in one Telegram message. Switching the configured schedule
  source or diary parser establishes a fresh baseline without reporting parser
  differences as updates. A date falling out of the rolling schedule window is
  not treated as a cancellation.
- Unchanged state is not written to Firestore.
- A missing-page response (`ページがありません`) or HTTP 404 sends one alert,
  even on the first run. Repeated failures are suppressed; recovery sends one
  alert and resets the observed diary/schedule baseline.
- Telegram delivery and Firestore writes cannot be committed atomically; a
  successful send followed by a failed state write can cause a retry to repeat
  that message.
- The first run sends a setup/test message with the current schedule, then saves
  the initial baseline.

See [GCP_DEPLOYMENT.md](GCP_DEPLOYMENT.md) for live GCP resource settings and
operations, and [FIRESTORE_SCHEMA.md](FIRESTORE_SCHEMA.md) for the state
document schema.

## Tests

Run the parser and notification-flow unit tests locally with:

```bash
uv run python -m unittest discover -s tests
```

## Local development

Create `.env.local` from `.env.local.example`, then run:

```bash
set -a
source .env.local
set +a
STATE_BACKEND=json uv run check_diary.py
```

The local JSON state is stored in `.cityheaven-state/state.json`. Do not run the
local launchd job at the same time as the GCP Scheduler job, or both may send
notifications.

To install the optional macOS launchd job, create `.env.local`, then run:

```bash
chmod +x run_local.sh
mkdir -p logs "$HOME/Library/LaunchAgents"
cp launchd/com.haoyang.cityheaven-diary-alert.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.haoyang.cityheaven-diary-alert.plist"
```

It runs at minute 5 and 35 of each hour. Stop it with:

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.haoyang.cityheaven-diary-alert.plist"
```
