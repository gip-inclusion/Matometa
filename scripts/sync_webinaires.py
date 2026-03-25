#!/usr/bin/env python3
"""Sync webinaire attendance data from Livestorm and Grist into datalake."""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.webinaires import (
    T_INSCRIPTIONS,
    T_SESSIONS,
    T_SYNC_META,
    T_WEBINAIRES,
    DatalakeWriter,
    GristClient,
    LivestormClient,
    sync_grist,
    sync_livestorm,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(description="Sync webinaire attendance data")
    parser.add_argument("--grist-only", action="store_true", help="Only sync Grist (for daily cron)")
    parser.add_argument("--livestorm-only", action="store_true", help="Only sync Livestorm")
    args = parser.parse_args()

    conn = DatalakeWriter()

    print("=" * 50)
    print("WEBINAIRES SYNC")
    print("=" * 50)
    print("Target: datalake (Metabase API)")
    print(f"Mode: {'grist-only' if args.grist_only else 'livestorm-only' if args.livestorm_only else 'full'}")
    print()

    t0 = time.time()
    results = {}

    # Livestorm sync
    if not args.grist_only:
        print("=" * 50)
        print("LIVESTORM SYNC")
        print("=" * 50)
        try:
            client = LivestormClient()
            events, sessions, regs = sync_livestorm(conn, client)
            results["livestorm"] = {
                "events": events,
                "sessions": sessions,
                "registrations": regs,
                "api_calls": client.request_count,
                "monthly_remaining": client.monthly_remaining,
            }
            print(
                f"\n  Livestorm: {events} events, {sessions} sessions, "
                f"{regs} registrations, {client.request_count} API calls"
            )
            if client.monthly_remaining is not None:
                print(f"  Monthly API budget remaining: {client.monthly_remaining}")
        except Exception as e:
            print(f"\n  ERROR: Livestorm sync failed: {e}")
            results["livestorm"] = {"error": str(e)}
        print()

    # Grist sync
    if not args.livestorm_only:
        print("=" * 50)
        print("GRIST SYNC")
        print("=" * 50)
        try:
            client = GristClient()
            webinaires, regs = sync_grist(conn, client)
            results["grist"] = {
                "webinaires": webinaires,
                "registrations": regs,
                "api_calls": client.request_count,
            }
            print(f"\n  Grist: {webinaires} webinaires, {regs} registrations")
        except Exception as e:
            print(f"\n  ERROR: Grist sync failed: {e}")
            results["grist"] = {"error": str(e)}
        print()

    # Store sync metadata
    total_time = time.time() - t0
    now = datetime.now(tz=timezone.utc).isoformat()

    total_webinars = conn.execute(f"SELECT COUNT(*) FROM {T_WEBINAIRES}").fetchone()[0]
    total_sessions = conn.execute(f"SELECT COUNT(*) FROM {T_SESSIONS}").fetchone()[0]
    total_regs = conn.execute(f"SELECT COUNT(*) FROM {T_INSCRIPTIONS}").fetchone()[0]
    unique_emails = conn.execute(f"SELECT COUNT(DISTINCT email) FROM {T_INSCRIPTIONS}").fetchone()[0]

    for key, value in [
        ("last_sync", now),
        ("sync_duration_seconds", str(round(total_time, 1))),
        ("total_webinars", str(total_webinars)),
        ("total_sessions", str(total_sessions)),
        ("total_registrations", str(total_regs)),
        ("unique_emails", str(unique_emails)),
    ]:
        conn.execute(
            f"""INSERT INTO {T_SYNC_META} (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value),
        )

    # Summary
    print("=" * 50)
    print("SYNC COMPLETE")
    print("=" * 50)
    print(f"Total time:      {total_time:.1f}s ({total_time / 60:.1f} min)")
    print(f"Webinars:        {total_webinars}")
    print(f"Sessions:        {total_sessions}")
    print(f"Registrations:   {total_regs}")
    print(f"Unique emails:   {unique_emails}")

    # Exit with error if any source failed
    for source, info in results.items():
        if "error" in info:
            sys.exit(1)


if __name__ == "__main__":
    main()
