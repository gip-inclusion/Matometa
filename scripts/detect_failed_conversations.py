#!/usr/bin/env python3
"""Detect conversations where Matometa likely failed (errors, corrections, omissions).

Scans assistant messages for failure markers. Useful for manual/batch review.
Real-time detection is handled by web/pm.py on each assistant response.

Usage:
    python scripts/detect_failed_conversations.py              # send DM
    python scripts/detect_failed_conversations.py --dry-run    # list without sending
    python scripts/detect_failed_conversations.py --days 14    # scan last 14 days
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from lib.failure_detection import FAILURE_MARKERS, extract_snippet
from web import config
from web.db import get_db
from web.schema import init_db


def slack_lookup_user(token: str, email: str) -> str | None:
    """Resolve an email to a Slack user ID."""
    resp = requests.get(
        "https://slack.com/api/users.lookupByEmail",
        headers={"Authorization": f"Bearer {token}"},
        params={"email": email},
        timeout=10,
    )
    data = resp.json()
    return data["user"]["id"] if data.get("ok") else None


def slack_send_dm(token: str, user_id: str, text: str) -> bool:
    """Send a DM to a Slack user."""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": user_id, "text": text},
        timeout=10,
    )
    return resp.json().get("ok", False)


NOTIFY_EMAIL = os.getenv("EMAIL_ANNAELLE", "")


def get_failed_conversations(days: int) -> list[dict]:
    """Find conversations with assistant messages containing failure markers."""
    init_db()

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    # Build LIKE clauses for each marker
    like_clauses = " OR ".join(["LOWER(m.content) LIKE ?" for _ in FAILURE_MARKERS])
    params = [f"%{marker}%" for marker in FAILURE_MARKERS]

    sql = f"""
        SELECT DISTINCT c.id, c.title, m.content
        FROM conversations c
        JOIN messages m ON m.conversation_id = c.id
        WHERE m.role = 'assistant'
          AND c.updated_at >= ?
          AND ({like_clauses})
        ORDER BY c.updated_at DESC
    """

    with get_db() as conn:
        rows = conn.execute(sql, (cutoff, *params)).fetchall()

    # Deduplicate by conversation id, keep first match
    seen = set()
    results = []
    for row in rows:
        conv_id = row["id"]
        if conv_id in seen:
            continue
        seen.add(conv_id)
        snip = extract_snippet(row["content"])
        results.append(
            {
                "id": conv_id,
                "title": row["title"] or "Sans titre",
                "snippet": snip,
            }
        )

    return results


def build_slack_message(conversations: list[dict]) -> str:
    """Build a grouped Slack message with conversation links."""
    base_url = config.BASE_URL

    lines = [":mag: *Conversations à vérifier*\n"]
    for conv in conversations:
        url = f"{base_url}/explorations/{conv['id']}"
        title = conv["title"]
        snippet = conv["snippet"]
        lines.append(f'• <{url}|{title}> — "{snippet}"')

    lines.append(f"\n{len(conversations)} conversation(s) détectée(s)")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Detect failed conversations")
    parser.add_argument("--dry-run", action="store_true", help="List detected conversations without sending")
    parser.add_argument("--days", type=int, default=7, help="Number of days to look back (default: 7)")
    args = parser.parse_args()

    conversations = get_failed_conversations(args.days)
    print(f"Found {len(conversations)} conversation(s) with failure markers (last {args.days} days)")

    if not conversations:
        print("Nothing to report.")
        return

    if args.dry_run:
        for conv in conversations:
            print(f'  [{conv["id"][:8]}] {conv["title"]} — "{conv["snippet"]}"')
        print("\nSlack message preview:\n")
        print(build_slack_message(conversations))
        return

    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        print("ERROR: SLACK_BOT_TOKEN is not set", file=sys.stderr)
        sys.exit(1)

    if not NOTIFY_EMAIL:
        print("ERROR: EMAIL_ANNAELLE is not set", file=sys.stderr)
        sys.exit(1)

    slack_id = slack_lookup_user(token, NOTIFY_EMAIL)
    if not slack_id:
        print(f"ERROR: Could not find Slack user for {NOTIFY_EMAIL}", file=sys.stderr)
        sys.exit(1)

    message = build_slack_message(conversations)
    ok = slack_send_dm(token, slack_id, message)
    if ok:
        print(f"Slack DM sent to {NOTIFY_EMAIL}")
    else:
        print(f"FAILED to send Slack DM to {NOTIFY_EMAIL}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
