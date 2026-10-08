"""Project-scoped budget notification handler that disables billing at the cap."""

from __future__ import annotations

import base64
import json
import logging
import os
from decimal import Decimal, InvalidOperation

import functions_framework
from google.cloud import billing_v1


PROJECT_ID = os.environ["TARGET_PROJECT_ID"]
EXPECTED_BUDGET_NAME = os.environ["EXPECTED_BUDGET_NAME"]
EXPECTED_BUDGET_AMOUNT = Decimal(os.environ["EXPECTED_BUDGET_AMOUNT"])
EXPECTED_CURRENCY = os.environ["EXPECTED_CURRENCY"]
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

_billing_client = billing_v1.CloudBillingClient()


@functions_framework.cloud_event
def stop_billing(event) -> None:
    """Disable billing for only the configured project after its budget cap."""
    message = event.data.get("message", {})
    encoded_data = message.get("data")
    if not encoded_data:
        logging.warning("Ignoring budget notification with no message data")
        return

    try:
        notification = json.loads(base64.b64decode(encoded_data))
        cost = Decimal(str(notification["costAmount"]))
        budget = Decimal(str(notification["budgetAmount"]))
    except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError):
        logging.exception("Ignoring malformed budget notification")
        return

    if notification.get("budgetDisplayName") != EXPECTED_BUDGET_NAME:
        logging.info("Ignoring notification for a different budget")
        return
    if notification.get("currencyCode") != EXPECTED_CURRENCY:
        logging.error("Ignoring notification with unexpected currency")
        return
    if budget != EXPECTED_BUDGET_AMOUNT:
        logging.error("Ignoring notification with unexpected budget amount")
        return
    if cost < budget:
        logging.info("Budget threshold not reached: %s / %s", cost, budget)
        return

    project_name = f"projects/{PROJECT_ID}"
    project_info = _billing_client.get_project_billing_info(name=project_name)
    if not project_info.billing_enabled:
        logging.info("Billing is already disabled for %s", PROJECT_ID)
        return

    if DRY_RUN:
        logging.critical(
            "DRY RUN: would disable billing for %s at %s %s",
            PROJECT_ID,
            cost,
            EXPECTED_CURRENCY,
        )
        return

    _billing_client.update_project_billing_info(
        name=project_name,
        project_billing_info=billing_v1.ProjectBillingInfo(billing_account_name=""),
    )
    logging.critical("Disabled billing for project %s at the configured budget cap", PROJECT_ID)
