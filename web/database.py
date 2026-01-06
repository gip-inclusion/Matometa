"""SQLite database for conversation persistence."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config
from .storage import Conversation, Message

# Database path
DB_PATH = config.BASE_DIR / "data" / "matometa.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Initialize database schema."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                session_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                raw_events TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id);

            CREATE INDEX IF NOT EXISTS idx_conversations_updated
                ON conversations(updated_at DESC);
        """)


class SQLiteConversationStore:
    """SQLite-backed conversation store."""

    def __init__(self):
        init_db()

    def create(self, user_id: Optional[str] = None) -> Conversation:
        """Create a new conversation."""
        import uuid
        conv = Conversation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=None,
        )

        with get_db() as conn:
            conn.execute(
                """INSERT INTO conversations (id, user_id, title, session_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (conv.id, conv.user_id, conv.title, conv.session_id,
                 conv.created_at.isoformat(), conv.updated_at.isoformat())
            )

        return conv

    def get(self, conv_id: str) -> Optional[Conversation]:
        """Get a conversation by ID with all messages."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()

            if not row:
                return None

            # Load messages
            msg_rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp",
                (conv_id,)
            ).fetchall()

            messages = [
                Message(
                    role=m["role"],
                    content=m["content"],
                    timestamp=datetime.fromisoformat(m["timestamp"]),
                    raw_events=json.loads(m["raw_events"]) if m["raw_events"] else [],
                )
                for m in msg_rows
            ]

            return Conversation(
                id=row["id"],
                user_id=row["user_id"],
                title=row["title"],
                messages=messages,
                session_id=row["session_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def append_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        raw_events: Optional[list[dict]] = None,
    ) -> Optional[Message]:
        """Append a message to a conversation."""
        msg = Message(
            role=role,
            content=content,
            raw_events=raw_events or [],
        )

        with get_db() as conn:
            # Check conversation exists
            row = conn.execute(
                "SELECT id, title FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if not row:
                return None

            # Insert message
            conn.execute(
                """INSERT INTO messages (conversation_id, role, content, raw_events, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (conv_id, role, content,
                 json.dumps(raw_events) if raw_events else None,
                 msg.timestamp.isoformat())
            )

            # Update conversation
            now = datetime.now().isoformat()

            # Auto-generate title from first user message
            if row["title"] is None and role == "user":
                title = content[:50] + ("..." if len(content) > 50 else "")
                conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (title, now, conv_id)
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conv_id)
                )

        return msg

    def update_session_id(self, conv_id: str, session_id: str) -> bool:
        """Update the agent session ID for a conversation."""
        with get_db() as conn:
            cursor = conn.execute(
                "UPDATE conversations SET session_id = ? WHERE id = ?",
                (session_id, conv_id)
            )
            return cursor.rowcount > 0

    def list_recent(
        self, user_id: Optional[str] = None, limit: int = 20
    ) -> list[Conversation]:
        """List recent conversations (without loading all messages)."""
        with get_db() as conn:
            if user_id:
                rows = conn.execute(
                    """SELECT c.*, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       WHERE c.user_id = ?
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC
                       LIMIT ?""",
                    (user_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT c.*, COUNT(m.id) as message_count
                       FROM conversations c
                       LEFT JOIN messages m ON m.conversation_id = c.id
                       GROUP BY c.id
                       ORDER BY c.updated_at DESC
                       LIMIT ?""",
                    (limit,)
                ).fetchall()

            return [
                Conversation(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    messages=[],  # Not loaded for list view
                    session_id=row["session_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in rows
            ]

    def delete(self, conv_id: str) -> bool:
        """Delete a conversation and its messages."""
        with get_db() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            return cursor.rowcount > 0
