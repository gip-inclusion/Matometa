#!/usr/bin/env python3
"""Wishlist - log capability requests and improvement ideas."""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

# Database path
DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "matometa.db"

CATEGORIES = ["tool", "knowledge", "skill", "workflow", "other"]


def init_db():
    """Initialize wishlist table if not exists."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            conversation_id TEXT,
            status TEXT DEFAULT 'open'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_wishlist_category
        ON wishlist(category)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_wishlist_status
        ON wishlist(status)
    """)
    conn.commit()
    conn.close()


def add_wish(category: str, title: str, description: str = None, conversation_id: str = None):
    """Add a new wish to the database."""
    if category not in CATEGORIES:
        print(f"Error: category must be one of {CATEGORIES}")
        return False

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """INSERT INTO wishlist (timestamp, category, title, description, conversation_id)
           VALUES (?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), category, title, description, conversation_id)
    )
    conn.commit()

    # Get the ID of the inserted row
    cursor = conn.execute("SELECT last_insert_rowid()")
    wish_id = cursor.fetchone()[0]
    conn.close()

    print(f"Added wish #{wish_id}: [{category}] {title}")
    return True


def list_wishes(category: str = None, status: str = "open", limit: int = 20):
    """List wishes from the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM wishlist WHERE 1=1"
    params = []

    if category:
        query += " AND category = ?"
        params.append(category)

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        print("No wishes found.")
        return

    print(f"{'ID':<4} {'Date':<12} {'Category':<10} {'Title'}")
    print("-" * 60)
    for row in rows:
        date = row["timestamp"][:10]
        print(f"{row['id']:<4} {date:<12} {row['category']:<10} {row['title']}")
        if row["description"]:
            # Indent description
            for line in row["description"].split("\n"):
                print(f"     {line}")


def update_status(wish_id: int, status: str):
    """Update wish status (open, done, wontfix)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE wishlist SET status = ? WHERE id = ?",
        (status, wish_id)
    )
    conn.commit()
    conn.close()
    print(f"Updated wish #{wish_id} to status: {status}")


def stats():
    """Show wishlist statistics."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # By category
    print("By category:")
    rows = conn.execute("""
        SELECT category, COUNT(*) as count
        FROM wishlist
        WHERE status = 'open'
        GROUP BY category
        ORDER BY count DESC
    """).fetchall()
    for row in rows:
        print(f"  {row['category']}: {row['count']}")

    # By status
    print("\nBy status:")
    rows = conn.execute("""
        SELECT status, COUNT(*) as count
        FROM wishlist
        GROUP BY status
    """).fetchall()
    for row in rows:
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

    args = parser.parse_args()

    # Initialize DB
    init_db()

    if args.command == "add":
        add_wish(args.category, args.title, args.description, args.conversation_id)
    elif args.command == "list":
        status = None if args.all else args.status
        list_wishes(args.category, status, args.limit)
    elif args.command == "update":
        update_status(args.id, args.status)
    elif args.command == "stats":
        stats()


if __name__ == "__main__":
    main()
