#!/usr/bin/env python3
"""Wishlist - log capability requests and improvement ideas."""

import argparse
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

# Notion config
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_WISHLIST_DB = os.getenv("NOTION_WISHLIST_DB")

CATEGORIES = ["permission", "tool", "knowledge", "skill", "workflow", "other"]


def _get_conn():
    """Get a PostgreSQL connection."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in .env")
    return psycopg2.connect(DATABASE_URL)


def push_to_notion(title: str, category: str, description: str = None) -> str | None:
    """Create a page in Notion wishlist database. Returns page ID or None."""
    if not NOTION_TOKEN or not NOTION_WISHLIST_DB:
        return None

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    # Build page properties (must match Notion database schema)
    properties = {
        "Fonction": {"title": [{"text": {"content": title}}]},
        "Catégorie": {"select": {"name": category}},
        "Statut": {"status": {"name": "En attente"}},
        "Source": {"rich_text": [{"text": {"content": "Matometa"}}]},
    }
    if description:
        properties["Description"] = {"rich_text": [{"text": {"content": description}}]}

    children = []

    payload = {
        "parent": {"database_id": NOTION_WISHLIST_DB},
        "properties": properties,
    }
    if children:
        payload["children"] = children

    try:
        req = urllib.request.Request(
            "https://api.notion.com/v1/pages",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                page_id = data.get("id")
                print(f"  → Synced to Notion")
                return page_id
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")[:100]
        print(f"  → Notion sync failed: {e.code} {body}")
        return None
    except Exception as e:
        print(f"  → Notion sync error: {e}")
        return None


def add_wish(category: str, title: str, description: str = None, conversation_id: str = None):
    """Add a new wish to the database."""
    if category not in CATEGORIES:
        print(f"Error: category must be one of {CATEGORIES}")
        return False

    # Push to Notion first
    notion_page_id = push_to_notion(title, category, description)

    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """INSERT INTO wishlist (timestamp, category, title, description, conversation_id, notion_page_id)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (datetime.now().isoformat(), category, title, description, conversation_id, notion_page_id)
    )
    wish_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()

    print(f"Added wish #{wish_id}: [{category}] {title}")
    return True


def list_wishes(category: str = None, status: str = "open", limit: int = 20):
    """List wishes from the database."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    query = "SELECT * FROM wishlist WHERE 1=1"
    params = []

    if category:
        query += " AND category = %s"
        params.append(category)

    if status:
        query += " AND status = %s"
        params.append(status)

    query += " ORDER BY timestamp DESC LIMIT %s"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No wishes found.")
        return

    print(f"{'ID':<4} {'Date':<12} {'Category':<10} {'Title'}")
    print("-" * 60)
    for row in rows:
        date = row["timestamp"][:10] if isinstance(row["timestamp"], str) else row["timestamp"].strftime("%Y-%m-%d")
        print(f"{row['id']:<4} {date:<12} {row['category']:<10} {row['title']}")
        if row["description"]:
            for line in row["description"].split("\n"):
                print(f"     {line}")


def update_status(wish_id: int, status: str):
    """Update wish status (open, done, wontfix)."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE wishlist SET status = %s WHERE id = %s",
        (status, wish_id)
    )
    conn.commit()
    conn.close()
    print(f"Updated wish #{wish_id} to status: {status}")


def sync_to_notion():
    """Sync all wishes without a notion_page_id to Notion."""
    if not NOTION_TOKEN or not NOTION_WISHLIST_DB:
        print("Error: NOTION_TOKEN and NOTION_WISHLIST_DB must be set")
        return

    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM wishlist WHERE notion_page_id IS NULL ORDER BY timestamp"
    )
    rows = cur.fetchall()

    if not rows:
        print("All wishes already synced to Notion.")
        conn.close()
        return

    print(f"Syncing {len(rows)} wishes to Notion...")
    synced = 0
    for row in rows:
        page_id = push_to_notion(row["title"], row["category"], row["description"])
        if page_id:
            cur.execute(
                "UPDATE wishlist SET notion_page_id = %s WHERE id = %s",
                (page_id, row["id"])
            )
            conn.commit()
            synced += 1
            print(f"  #{row['id']}: {row['title']}")

    conn.close()
    print(f"Synced {synced}/{len(rows)} wishes.")


def stats():
    """Show wishlist statistics."""
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # By category
    print("By category:")
    cur.execute("""
        SELECT category, COUNT(*) as count
        FROM wishlist
        WHERE status = 'open'
        GROUP BY category
        ORDER BY count DESC
    """)
    for row in cur.fetchall():
        print(f"  {row['category']}: {row['count']}")

    # By status
    print("\nBy status:")
    cur.execute("""
        SELECT status, COUNT(*) as count
        FROM wishlist
        GROUP BY status
    """)
    for row in cur.fetchall():
        print(f"  {row['status']}: {row['count']}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Manage capability wishlist")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new wish")
    add_parser.add_argument("--category", "-c", required=True, choices=CATEGORIES)
    add_parser.add_argument("--title", "-t", required=True)
    add_parser.add_argument("--description", "-d")
    add_parser.add_argument("--conversation-id")

    # List command
    list_parser = subparsers.add_parser("list", help="List wishes")
    list_parser.add_argument("--category", "-c", choices=CATEGORIES)
    list_parser.add_argument("--status", "-s", default="open")
    list_parser.add_argument("--limit", "-n", type=int, default=20)
    list_parser.add_argument("--all", "-a", action="store_true", help="Show all statuses")

    # Update command
    update_parser = subparsers.add_parser("update", help="Update wish status")
    update_parser.add_argument("id", type=int)
    update_parser.add_argument("--status", "-s", required=True, choices=["open", "done", "wontfix"])

    # Stats command
    subparsers.add_parser("stats", help="Show statistics")

    # Sync command
    subparsers.add_parser("sync", help="Sync unsynced wishes to Notion")

    args = parser.parse_args()

    if args.command == "add":
        add_wish(args.category, args.title, args.description, args.conversation_id)
    elif args.command == "list":
        status = None if args.all else args.status
        list_wishes(args.category, status, args.limit)
    elif args.command == "update":
        update_status(args.id, args.status)
    elif args.command == "stats":
        stats()
    elif args.command == "sync":
        sync_to_notion()


if __name__ == "__main__":
    main()
