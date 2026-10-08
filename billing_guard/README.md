# GCP budget shutdown guard

This Gen 2 Cloud Function handles notifications for the project-wide GCP
budget. It is deployed in project `my-crawler-project-510912`, region
`asia-east1`, as `budget-shutdown-guard`. The dedicated Pub/Sub trigger is
`project-budget-shutdown`; the budget is `project-monthly-hard-stop`, set to
TWD 1/month for the entire project with credits included.

The function ignores malformed notifications and notifications that do not
match the expected budget display name, budget amount, currency, or target
project. It also ignores costs below the configured amount. At or above the
amount, it unlinks billing from the configured project if billing is still
enabled. See [`../GCP_DEPLOYMENT.md`](../GCP_DEPLOYMENT.md) for the full
resource inventory, other Cloud Run spend cap, and crawler deployment plan.

## Deployed configuration

- Runtime: Python 3.12, 256 MiB, 60-second timeout, maximum 1 instance.
- Service account:
  `budget-shutdown-guard@my-crawler-project-510912.iam.gserviceaccount.com`.
- Environment variables: `TARGET_PROJECT_ID=my-crawler-project-510912`,
  `EXPECTED_BUDGET_NAME=project-monthly-hard-stop`,
  `EXPECTED_BUDGET_AMOUNT=1`, `EXPECTED_CURRENCY=TWD`, `DRY_RUN=false`.
- IAM: `roles/billing.projectManager` and `roles/browser` on the target
  project; `roles/eventarc.eventReceiver` on the project; and
  `roles/run.invoker` on the backing function service.

The function account has project-scoped billing permission; it does not have
Billing Account Administrator access. The implementation reads only the
configured project and budget event, then detaches that project's billing
account when the threshold is met.

## Deploy and test safely

Deploy from the repository root with `billing_guard/` as the source. Using
the repository root as source selects the crawler's `main.py` and the wrong
entry point:

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

For an end-to-end handler test, deploy with `DRY_RUN=true` and publish a
synthetic Pub/Sub notification whose cost is above TWD 1. Confirm the log says
`DRY RUN: would disable billing ...`; then restore `DRY_RUN=false`. A
below-threshold notification was also checked. The real unlink action has not
been invoked: it would suspend billing for the project. The deployed function
is currently ACTIVE, and project billing remains linked.

Do not use a real budget-crossing event as a test. Budget notifications can
arrive after usage and are not a real-time spending guarantee. If the guard
does unlink billing, restore it manually in the Cloud Console before expecting
project services to resume.
