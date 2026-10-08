"""HTTP entry point for a private Cloud Run function."""

from __future__ import annotations

import logging

from check_diary import run_check


def check(request):
    """Cloud Scheduler invokes this function with an authenticated POST."""
    if request.method != "POST":
        return ("Method Not Allowed", 405)
    try:
        run_check()
    except Exception:
        logging.exception("Scheduled monitor execution failed")
        return ("Monitor execution failed", 500)
    return ("Monitor completed", 200)
