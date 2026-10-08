# GCP deployment and operations

This document records the live GCP setup for this repository. The budget
shutdown guard, Firestore database, diary monitor, and 30-minute Cloud Scheduler
job are deployed. GCP Scheduler is the only configured production scheduler.

## Current project

| Setting | Value |
| --- | --- |
| Project ID | `my-crawler-project-510912` |
| Project number | `681390990254` |
| Billing currency | TWD (NT$) |
| Region used for GCP resources | `asia-east1` |
| Project state | Active; billing linked |

The project contains two workloads: the budget shutdown guard and the diary
monitor service. The Cloud Run service named `budget-shutdown-guard` is the
underlying service for the Gen 2 Cloud Function.

## Cloud Logging and housekeeping

The project uses only the system-created `_Default` and `_Required` log
buckets; there are no custom log export sinks. `_Default` retains logs for 30
days, and `_Required` retains required audit logs for 400 days. These are the
currently reported bucket settings.

The `logging.googleapis.com/billing/bytes_ingested` metric reported 2,063,698
bytes (about 1.97 MiB) ingested from 2026-10-01 through 2026-10-08 06:05 UTC.
Cloud Logging includes the first 50 GiB per project per month, and the default
30-day retention does not incur an extra retention charge. The `_Required`
bucket has no storage charge. At this measured volume, log ingestion and
retention are well within the free usage range.

No cleanup job is needed: Cloud Logging applies bucket retention automatically.
The `_Default` bucket is already at the default 30-day retention, while
`_Required` retention is fixed by Google Cloud.

Firestore database `(default)` was created on 2026-10-08 (Taipei time) in
`asia-east1` in Native mode. GCP reports `freeTier: true`. Firestore creates
collections and documents on first write, so the `monitor_targets` collection
is created when the monitor's first state save succeeds.

## Cost controls already configured

Two monthly budgets serve different purposes:

| Budget | Scope and amount | Credits | Thresholds and action |
| --- | --- | --- | --- |
| `cloud-run-spend-cap` | This project, Cloud Run service `services/152E-C115-5142`, TWD 20/month | Excluded (`EXCLUDE_ALL_CREDITS`), so the cap tracks gross Cloud Run cost | 50%, 80%, 100%; Cloud Run spend cap is configured to pause Cloud Run usage at the cap |
| `project-monthly-hard-stop` | Entire project `681390990254`, TWD 1/month | Included (`INCLUDE_ALL_CREDITS`) | 50%, 80%, 100%; Pub/Sub notification triggers the guard, which unlinks project billing once reported cost reaches the budget amount |

The project budget uses the topic `project-budget-shutdown`. Its budget ID is
`dd9eeca6-d2cc-48fc-8351-b394b71c9d86`; the Cloud Run budget ID is
`78d6cedd-42df-4ede-8f3c-92b1883d8e85`.

The project-wide budget can stop billing for all billable project services,
including services that otherwise fall within a free tier. Google Cloud
budget notifications are based on reported billing data and may be delayed;
they are not a hard real-time guarantee against charges. Once billing is
unlinked, it must be linked again manually in the Cloud Console before the
project's services can resume.

### Budget shutdown guard resources

- Gen 2 Cloud Function: `budget-shutdown-guard`
- Region and runtime: `asia-east1`, Python 3.12
- Trigger: Pub/Sub topic `project-budget-shutdown`
- Function service account:
  `budget-shutdown-guard@my-crawler-project-510912.iam.gserviceaccount.com`
- Memory, timeout, maximum instances: 256 MiB, 60 seconds, 1
- Environment: `TARGET_PROJECT_ID=my-crawler-project-510912`,
  `EXPECTED_BUDGET_NAME=project-monthly-hard-stop`,
  `EXPECTED_BUDGET_AMOUNT=1`, `EXPECTED_CURRENCY=TWD`, `DRY_RUN=false`
- Build artifacts: Artifact Registry Docker repository `gcf-artifacts` and
  source bucket `gcf-v2-sources-681390990254-asia-east1`, both in `asia-east1`.

The handler in [`billing_guard/main.py`](billing_guard/main.py) validates the
budget display name, amount, currency, and configured project. It does nothing
below the budget amount and checks whether billing is already disabled before
acting. At or above the amount, it unlinks billing from the one configured
project. The service account has project-scoped `roles/billing.projectManager`
and `roles/browser`, plus `roles/eventarc.eventReceiver` and
`roles/run.invoker` on the function's Cloud Run service. It does not have
Billing Account Administrator access.

### Setup actions and verification

The GCP APIs enabled or confirmed for this setup include Billing Budgets,
Cloud Billing, Cloud Build, Cloud Functions, Cloud Scheduler, Eventarc,
Firestore, Pub/Sub, Cloud Run, Artifact Registry, Cloud Logging, and Secret
Manager.

The function deployment must use `billing_guard/` as its source directory so
the Gen 2 entry point resolves to `stop_billing`:

```bash
gcloud config set project my-crawler-project-510912
gcloud functions deploy budget-shutdown-guard \
  --gen2 \
  --runtime python312 \
  --region asia-east1 \
  --source billing_guard \
  --entry-point stop_billing \
  --trigger-topic project-budget-shutdown \
  --service-account budget-shutdown-guard@my-crawler-project-510912.iam.gserviceaccount.com \
  --memory 256MiB \
  --timeout 60s \
  --max-instances 1 \
  --set-env-vars TARGET_PROJECT_ID=my-crawler-project-510912,EXPECTED_BUDGET_NAME=project-monthly-hard-stop,EXPECTED_BUDGET_AMOUNT=1,EXPECTED_CURRENCY=TWD,DRY_RUN=false
```

For a safe handler-path check, temporarily deploy with `DRY_RUN=true` and
publish a synthetic Pub/Sub budget notification whose cost is above TWD 1.
The function logged that it *would* disable billing. A below-threshold test
also completed, and project billing remained enabled. The real unlink action
was not triggered or tested because it would suspend project billing. Restore
`DRY_RUN=false` after a dry-run check.

During setup, Eventarc delivery initially lacked permissions; adding
`roles/eventarc.eventReceiver` to the function service account and
`roles/run.invoker` to that account on the backing Cloud Run service resolved
it. An initial deployment from the repository root selected the wrong entry
point; deploying with `--source billing_guard` fixed it. The currently
deployed function is ACTIVE.

## Diary and schedule monitor

The monitor is deployed as a private Cloud Run service and is invoked by one
authenticated Cloud Scheduler job.

| Resource | Live configuration |
| --- | --- |
| Cloud Run service | `diary-schedule-monitor`, `asia-east1`, Python 3.12, revision `diary-schedule-monitor-00009-5dp`, Ready |
| Service URL | `https://diary-schedule-monitor-w3233xwonq-de.a.run.app` |
| Authentication | Unauthenticated invocation disabled; `roles/run.invoker` is granted to the Scheduler service account only |
| Scaling | Request-based billing, minimum 0, maximum 1 instance, concurrency 1 |
| Instance resources | 1 vCPU, 512 MiB, 300-second request timeout |
| Runtime service account | `diary-monitor-runtime@my-crawler-project-510912.iam.gserviceaccount.com` |
| State | Firestore `(default)`, collection `monitor_targets`; schema in [`FIRESTORE_SCHEMA.md`](FIRESTORE_SCHEMA.md) |
| Telegram secrets | `telegram-bot-token:1` and `telegram-chat-id:1`, injected as environment variables |
| Scheduler | `diary-schedule-monitor`, `*/30 * * * *`, `Asia/Taipei`, enabled |
| Scheduler service account | `diary-monitor-scheduler@my-crawler-project-510912.iam.gserviceaccount.com` |

The runtime account has `roles/datastore.user` on the project and
`roles/secretmanager.secretAccessor` on only the two Telegram secrets. The
Scheduler account has `roles/run.invoker` on only the monitor service. The
Cloud Scheduler service agent retains `roles/cloudscheduler.serviceAgent`.

### Free-tier posture checked on 2026-10-08

These are usage allowances, not guarantees based only on resource specs.
Several free tiers are pooled across the billing account, so usage by other
projects can reduce the remaining allowance.

| Service | Current use/spec | Free-tier comparison |
| --- | --- | --- |
| Cloud Run monitor | One scheduled request every 30 minutes (about 1,440/month); 1 vCPU, 512 MiB, min 0/max 1 instance | 2 million requests, 180,000 vCPU-seconds, and 360,000 GiB-seconds/month. Actual compute usage depends on request duration and other project traffic. |
| Firestore | One default Native database; one document per monitor target; one document read per 30-minute poll and writes only on change | This database reports `freeTier: true`; allowance is 1 GiB stored data, 50,000 reads/day, and 20,000 writes/day. |
| Cloud Scheduler | One job, 48 scheduled executions/day | First three jobs per billing account are free; other projects on the account count toward the same limit. |
| Secret Manager | Two active version-1 secrets; injected at instance startup | Six active versions and 10,000 access operations/month are free per billing account. |
| Cloud Build | Source-based deployment builds | 2,500 build minutes/month are free per billing account. |
| Artifact Registry | `cloud-run-source-deploy`: 25.056 MB; `gcf-artifacts`: 47.776 MB; about 72.8 MB total | First 0.5 GiB-month of storage is free per billing account. |
| Budget guard / Eventarc | One low-volume Pub/Sub-triggered function, 256 MiB, max 1 instance, 60-second timeout | Invocation and compute use are far below the function free-tier allowances at the current notification volume. |

The monitor service has the minimum 512 MiB memory for its current second
generation execution environment, but 1 vCPU is not the lowest CPU value Cloud
Run supports in every execution environment. Fractional CPU requires the first
generation environment and request-based billing; this deployment remains at
1 vCPU.

The crawler fetches pages from the public internet and sends Telegram requests.
Outbound internet transfer from `asia-east1` can incur a small charge. The
current request sizes are expected to be small, but this and any free-tier
usage by other projects prevent guaranteeing a zero bill. The TWD 20 Cloud Run
spend cap and TWD 1 project shutdown budget are delayed safeguards, not hard
real-time caps.

The first invocation completed with HTTP 200, sent the initial Telegram
message, and saved the Firestore baseline. A subsequent manual Scheduler run
also reached Cloud Run with HTTP 200, exercising the configured OIDC path.
The real budget unlink action remains intentionally untested.

### Profile parser

The CityHeaven profile page contains both the diary entries and its
server-rendered `#girlprofile_sukkin` attendance schedule. Each poll fetches that
page once, then parses both sections. A visible `ページがありません` response
or HTTP 404 is recorded as unavailable and triggers one alert, including on an
initial run. The alert is suppressed while the page remains unavailable; a
recovery triggers one message and establishes a fresh baseline. Segretario is
not used by the deployed monitor.

After revision `diary-schedule-monitor-00009-5dp` was deployed, the 2026-10-08
06:00 UTC Scheduler invocation returned HTTP 200 on that revision. The
Firestore target document was updated with `availability=available` and both
current CityHeaven parser/source identifiers.

### Re-deploy after code changes

Run from the repository root. The account is private, and the environment
variables resolve to fixed secret version 1:

```bash
gcloud run deploy diary-schedule-monitor \
  --source . \
  --function check \
  --base-image python312 \
  --region asia-east1 \
  --service-account diary-monitor-runtime@my-crawler-project-510912.iam.gserviceaccount.com \
  --no-allow-unauthenticated \
  --cpu 1 \
  --memory 512Mi \
  --min 0 \
  --max 1 \
  --concurrency 1 \
  --timeout 300 \
  --set-env-vars STATE_BACKEND=firestore,FIRESTORE_COLLECTION=monitor_targets \
  --set-secrets TELEGRAM_BOT_TOKEN=telegram-bot-token:1,TELEGRAM_CHAT_ID=telegram-chat-id:1
```

The existing Scheduler job already targets the service URL with that URL as
the OIDC audience. To inspect it or manually run a normal deduplicated poll:

```bash
gcloud scheduler jobs describe diary-schedule-monitor \
  --project=my-crawler-project-510912 --location=asia-east1
gcloud scheduler jobs run diary-schedule-monitor \
  --project=my-crawler-project-510912 --location=asia-east1
```

Manually running the Scheduler job does not bypass Firestore comparison; it
only sends Telegram notifications when the observed diary or schedule meets
the regular change rules.

Later runs compare diary and schedule data with the previous snapshot and
notify on new or changed shifts, cancellations, and qualifying recent diary
posts. The Firestore document records parser/source identifiers; source
changes establish a baseline to prevent migration differences from being
reported as real updates. Cloud Run request usage, Firestore operations,
Scheduler jobs, Secret Manager versions, Cloud Build minutes, and Artifact Registry storage are
currently sized below their respective free-tier limits, assuming the billing
account's pooled free quotas are not already consumed elsewhere. Outbound
internet transfer to the monitored websites and Telegram can still incur a
small charge. The TWD 20 Cloud Run spend cap and TWD 1 project shutdown budget
are additional delayed safeguards, not a guarantee of zero charges.
