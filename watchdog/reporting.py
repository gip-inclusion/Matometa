"""Reporting: JSONL log + optional webhook."""

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

from watchdog import config

logger = logging.getLogger(__name__)


def log_event(event: dict):
    """Append event to the JSONL log file."""
    event["timestamp"] = datetime.now(timezone.utc).isoformat()

    path = config.LOG_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        with open(path, "a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error("Failed to write log: %s", e)


def send_webhook(event: dict):
    """Send event to webhook (Slack/Discord compatible)."""
    url = config.WEBHOOK_URL
    if not url:
        return

    severity = event.get("severity", "info")
    icon = {"info": "ℹ️", "warn": "⚠️", "critical": "🚨"}.get(severity, "📋")

    payload = {
        "text": f"{icon} **Watchdog [{severity.upper()}]**: {event.get('message', '')}",
    }

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.warning("Webhook failed: %s", e)
