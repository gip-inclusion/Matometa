#!/usr/bin/env python3
"""
Fix updated_at timestamps for conversations that were modified by the tag backfill.
Sets updated_at to the timestamp of the last message in each conversation.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.database import init_db, get_db


def fix_updated_at():
    """Reset updated_at for all conversations to their last message timestamp."""
    init_db()

    with get_db() as conn:
        # Find conversations where updated_at differs from their last message
        rows = conn.execute("""
            SELECT c.id, c.updated_at as conv_updated, m.last_msg
            FROM conversations c
            JOIN (
                SELECT conversation_id, MAX(timestamp) as last_msg
                FROM messages
                GROUP BY conversation_id
            ) m ON c.id = m.conversation_id
            WHERE c.updated_at != m.last_msg
        """).fetchall()

        print(f"Found {len(rows)} conversations with mismatched updated_at")

        for row in rows:
            conv_id = row["id"]
            old_ts = row["conv_updated"]
            new_ts = row["last_msg"]
            print(f"  {conv_id[:8]}... {old_ts} -> {new_ts}")

            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (new_ts, conv_id)
            )

        print(f"\nFixed {len(rows)} conversations")


if __name__ == "__main__":
    fix_updated_at()
