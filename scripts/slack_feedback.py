#!/usr/bin/env python3
"""Send weekly Slack DMs asking active users for Tally feedback.

Queries conversations updated in the last 7 days, resolves Slack user IDs
via email, and sends a short DM with a pre-filled Tally link.

Usage:
    python scripts/slack_feedback.py              # send DMs to all active users
    python scripts/slack_feedback.py --dry-run    # list targeted emails, don't send
    python scripts/slack_feedback.py --test EMAIL # send a single test DM
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from web.database import get_db, init_db

TALLY_FORM_URL = "https://tally.so/r/9qdZvp"

# Emails to exclude (system / bot accounts)
EXCLUDED_EMAILS = {"admin@localhost", ""}

SLACK_MESSAGE = (
    ":wave: Bonjour !\n\n"
    "Vous avez utilisé *Autometa* cette semaine — merci !\n"
    "Pourriez-vous prendre 2 minutes pour nous faire un retour ?\n\n"
    ":point_right: <{tally_url}|Donner mon feedback>\n\n"
    "Vos retours nous aident à améliorer l'outil. Merci :pray:"
)


def get_active_emails() -> list[str]:
    """Return distinct user emails with activity in the last 7 days."""
    init_db()

    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM conversations WHERE updated_at >= %s",
            (cutoff,),
        ).fetchall()

    emails = []
    for row in rows:
        email = row["user_id"]
        if email and email.strip() and email.strip() not in EXCLUDED_EMAILS:
            emails.append(email.strip())
    return sorted(set(emails))


def slack_lookup_user(token: str, email: str) -> str | None:
    """Resolve an email to a Slack user ID via users.lookupByEmail."""
    resp = requests.get(
        "https://slack.com/api/users.lookupByEmail",
        headers={"Authorization": f"Bearer {token}"},
        params={"email": email},
        timeout=10,
    )
    data = resp.json()
    if data.get("ok"):
        return data["user"]["id"]
    return None


def slack_send_dm(token: str, user_id: str, text: str) -> bool:
    """Send a DM to a Slack user (channel = user ID)."""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": user_id, "text": text},
        timeout=10,
    )
    data = resp.json()
    return data.get("ok", False)


def build_message(email: str) -> str:
    """Build the Slack message with a pre-filled Tally link."""
    tally_url = f"{TALLY_FORM_URL}?email={quote(email)}"
    return SLACK_MESSAGE.format(tally_url=tally_url)


def main():
    parser = argparse.ArgumentParser(description="Send weekly Slack feedback DMs")
    parser.add_argument("--dry-run", action="store_true", help="List targeted emails without sending")
    parser.add_argument("--test", metavar="EMAIL", help="Send a single test DM to this email")
    args = parser.parse_args()

    token = os.getenv("SLACK_BOT_TOKEN", "")
    if not token and not args.dry_run:
        print("ERROR: SLACK_BOT_TOKEN is not set", file=sys.stderr)
        sys.exit(1)

    if args.test:
        email = args.test
        print(f"Sending test DM to {email}...")
        slack_id = slack_lookup_user(token, email)
        if not slack_id:
            print(f"  Could not find Slack user for {email}", file=sys.stderr)
            sys.exit(1)
        ok = slack_send_dm(token, slack_id, build_message(email))
        print(f"  {'Sent' if ok else 'FAILED'}")
        sys.exit(0 if ok else 1)

    emails = get_active_emails()
    print(f"Found {len(emails)} active user(s) in the last 7 days")

    if args.dry_run:
        for email in emails:
            print(f"  {email}")
        return

    sent = 0
    failed = 0
    for email in emails:
        slack_id = slack_lookup_user(token, email)
        if not slack_id:
            print(f"  SKIP {email} (no Slack user found)")
            failed += 1
            continue
        ok = slack_send_dm(token, slack_id, build_message(email))
        if ok:
            print(f"  SENT {email}")
            sent += 1
        else:
            print(f"  FAIL {email}")
            failed += 1

    print(f"\nDone: {sent} sent, {failed} failed")


if __name__ == "__main__":
    main()
