#!/usr/bin/env python3
"""Backfill tool_use messages with taxonomy categories.

Adds a 'category' field to the JSON content of tool_use messages
for observability in the sidebar.

Usage:
    # Dry run (show what would be updated)
    python scripts/backfill_tool_taxonomy.py --dry-run

    # Actually update
    python scripts/backfill_tool_taxonomy.py

    # With custom database path
    python scripts/backfill_tool_taxonomy.py --db /path/to/matometa.db
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from lib.tool_taxonomy import classify_tool


def get_db_connection(db_path: str):
    """Get database connection (SQLite or PostgreSQL)."""
    if db_path.startswith("postgres"):
        import psycopg2
        return psycopg2.connect(db_path), "postgres"
    else:
        import sqlite3
        return sqlite3.connect(db_path), "sqlite"


def backfill(db_path: str, dry_run: bool = False):
    """Backfill tool_use messages with categories."""
    conn, db_type = get_db_connection(db_path)
    cur = conn.cursor()

    # Get all tool_use messages
    cur.execute("SELECT id, content FROM messages WHERE type = 'tool_use'")
    rows = cur.fetchall()

    updated = 0
    skipped = 0
    errors = 0

    for row in rows:
        msg_id, content = row
        try:
            data = json.loads(content)

            # Skip if already has category
            if "category" in data:
                skipped += 1
                continue

            # Classify
            tool_name = data.get("tool", "")
            tool_input = data.get("input", {})
            category = classify_tool(tool_name, tool_input)

            if dry_run:
                print(f"  [{msg_id}] {tool_name} -> {category}")
                updated += 1
                continue

            # Update
            data["category"] = category
            new_content = json.dumps(data)

            if db_type == "postgres":
                cur.execute(
                    "UPDATE messages SET content = %s WHERE id = %s",
                    (new_content, msg_id),
                )
            else:
                cur.execute(
                    "UPDATE messages SET content = ? WHERE id = ?",
                    (new_content, msg_id),
                )
            updated += 1

        except (json.JSONDecodeError, TypeError) as e:
            print(f"  Error on message {msg_id}: {e}", file=sys.stderr)
            errors += 1

    if not dry_run:
        conn.commit()

    conn.close()

    return updated, skipped, errors


def main():
    parser = argparse.ArgumentParser(description="Backfill tool taxonomy categories")
    parser.add_argument(
        "--db",
        default=str(project_root / "data" / "matometa.db"),
        help="Database path or PostgreSQL URL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    args = parser.parse_args()

    print(f"Database: {args.db}")
    print(f"Dry run: {args.dry_run}")
    print()

    updated, skipped, errors = backfill(args.db, args.dry_run)

    print()
    print(f"Updated: {updated}")
    print(f"Skipped (already tagged): {skipped}")
    print(f"Errors: {errors}")

    if args.dry_run and updated > 0:
        print()
        print("Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
