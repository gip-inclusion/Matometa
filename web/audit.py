"""Audit logging for agent tool usage.

Stores audit logs in a separate SQLite database for security and separation of concerns.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import config

# Separate database for audit logs
AUDIT_DB_PATH = config.BASE_DIR / "data" / "audit.db"


def get_audit_connection() -> sqlite3.Connection:
    """Get an audit database connection."""
    AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUDIT_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")
    return conn


@contextmanager
def get_audit_db():
    """Context manager for audit database connections."""
    conn = get_audit_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_audit_db():
    """Initialize the audit database schema."""
    with get_audit_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tool_invocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                user_email TEXT,
                tool_name TEXT NOT NULL,
                tool_input TEXT,
                success INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_tool_invocations_timestamp
                ON tool_invocations(timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_tool_invocations_user
                ON tool_invocations(user_email);

            CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool
                ON tool_invocations(tool_name);
        """)


# Initialize on import
init_audit_db()


def audit_log(
    conversation_id: str,
    tool_name: str,
    tool_input: Any,
    user_email: Optional[str] = None,
    success: bool = True,
) -> None:
    """
    Log a tool invocation to the audit database.

    Args:
        conversation_id: The conversation where the tool was invoked
        tool_name: Name of the tool (e.g., "Bash", "Read", "Write")
        tool_input: The input passed to the tool (will be JSON-serialized)
        user_email: Email of the authenticated user (from oauth2-proxy)
        success: Whether the tool invocation succeeded
    """
    try:
        input_json = json.dumps(tool_input) if tool_input else None
    except (TypeError, ValueError):
        input_json = str(tool_input)

    with get_audit_db() as conn:
        conn.execute(
            """INSERT INTO tool_invocations
               (timestamp, conversation_id, user_email, tool_name, tool_input, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().isoformat(),
                conversation_id,
                user_email,
                tool_name,
                input_json,
                1 if success else 0,
            )
        )


def get_recent_audit_logs(limit: int = 100) -> list[dict]:
    """Get recent audit log entries."""
    with get_audit_db() as conn:
        rows = conn.execute(
            """SELECT * FROM tool_invocations
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()

        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "conversation_id": row["conversation_id"],
                "user_email": row["user_email"],
                "tool_name": row["tool_name"],
                "tool_input": json.loads(row["tool_input"]) if row["tool_input"] else None,
                "success": bool(row["success"]),
            }
            for row in rows
        ]


def get_audit_logs_for_conversation(conversation_id: str) -> list[dict]:
    """Get all audit logs for a specific conversation."""
    with get_audit_db() as conn:
        rows = conn.execute(
            """SELECT * FROM tool_invocations
               WHERE conversation_id = ?
               ORDER BY timestamp ASC""",
            (conversation_id,)
        ).fetchall()

        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "tool_name": row["tool_name"],
                "tool_input": json.loads(row["tool_input"]) if row["tool_input"] else None,
                "success": bool(row["success"]),
            }
            for row in rows
        ]
