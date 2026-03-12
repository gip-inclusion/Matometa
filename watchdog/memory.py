"""Rolling memory for the watchdog agent.

Stores the last N reports in a JSONL file with a size cap.
Fed back into the agent's system prompt so it has context of recent actions.
"""

import json
import logging
import os
from datetime import datetime, timezone
from watchdog import config

logger = logging.getLogger(__name__)


def load_reports() -> list[dict]:
    """Load the last N reports from the memory file."""
    path = config.MEMORY_FILE
    if not os.path.exists(path):
        return []

    reports = []
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        reports.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError as e:
        logger.warning("Failed to read memory file: %s", e)
        return []

    # Keep only the last N reports
    return reports[-config.MEMORY_MAX_REPORTS:]


def append_report(report: dict):
    """Append a report to the memory file, enforcing size limits."""
    report["timestamp"] = datetime.now(timezone.utc).isoformat()

    path = config.MEMORY_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Append the new report
    try:
        with open(path, "a") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.error("Failed to write memory: %s", e)
        return

    # Enforce limits: max reports and max file size
    _enforce_limits(path)


def format_memory_for_prompt() -> str:
    """Format recent reports as a string for the system prompt."""
    reports = load_reports()
    if not reports:
        return "No previous reports. This is the first scan."

    lines = [f"## Last {len(reports)} reports (most recent last)"]
    for r in reports:
        ts = r.get("timestamp", "?")[:19]
        sev = r.get("severity", "info").upper()
        msg = r.get("summary", r.get("message", ""))
        actions = r.get("actions_taken", [])
        action_str = f" | Actions: {', '.join(actions)}" if actions else ""
        lines.append(f"- [{ts}] [{sev}] {msg}{action_str}")

    return "\n".join(lines)


def _enforce_limits(path: str):
    """Trim memory file to stay within max reports and max size."""
    try:
        # Check file size
        size_kb = os.path.getsize(path) / 1024
        reports = load_reports()

        needs_trim = (
            len(reports) > config.MEMORY_MAX_REPORTS
            or size_kb > config.MEMORY_MAX_SIZE_KB
        )

        if needs_trim:
            # Keep only the most recent reports that fit
            trimmed = reports[-config.MEMORY_MAX_REPORTS:]

            # If still too large, keep fewer
            while trimmed and _estimated_size_kb(trimmed) > config.MEMORY_MAX_SIZE_KB:
                trimmed.pop(0)

            # Rewrite file
            with open(path, "w") as f:
                for r in trimmed:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

            logger.debug("Memory trimmed: %d reports, ~%.1fKB",
                         len(trimmed), _estimated_size_kb(trimmed))

    except OSError as e:
        logger.warning("Failed to trim memory: %s", e)


def _estimated_size_kb(reports: list[dict]) -> float:
    return sum(len(json.dumps(r)) for r in reports) / 1024
