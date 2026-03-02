"""Audit logging for agent tool usage.

Uses the main PostgreSQL connection pool.
"""

import json
import logging
from typing import Any, Optional

from .db import get_db

logger = logging.getLogger(__name__)


def get_audit_db():
    """Context manager for audit database connections."""
    return get_db()


def init_audit_db():
    """Initialize the audit database schema."""
    with get_audit_db() as conn:
        conn.execute_raw("""
            CREATE TABLE IF NOT EXISTS tool_invocations (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                conversation_id TEXT NOT NULL,
                user_email TEXT,
                tool_name TEXT NOT NULL,
                tool_input TEXT,
                success BOOLEAN DEFAULT TRUE
            );

            CREATE INDEX IF NOT EXISTS idx_tool_invocations_timestamp
                ON tool_invocations(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_tool_invocations_user
                ON tool_invocations(user_email);
            CREATE INDEX IF NOT EXISTS idx_tool_invocations_tool
                ON tool_invocations(tool_name);

            DELETE FROM tool_invocations
                WHERE timestamp < NOW() - INTERVAL '90 days';
        """)


# Initialize on import
try:
    init_audit_db()
except Exception as e:
    logger.warning("Failed to initialize tool_invocations table: %s", e)


def audit_log(
    conversation_id: str,
    tool_name: str,
    tool_input: Any,
    user_email: Optional[str] = None,
    success: bool = True,
) -> None:
    """Log a tool invocation to the audit database."""
    try:
        input_json = json.dumps(tool_input) if tool_input else None
    except (TypeError, ValueError):
        input_json = str(tool_input)

    try:
        with get_audit_db() as conn:
            conn.execute(
                """INSERT INTO tool_invocations
                   (conversation_id, user_email, tool_name, tool_input, success)
                   VALUES (%s, %s, %s, %s, %s)""",
                (conversation_id, user_email, tool_name, input_json, 1 if success else 0),
            )
    except Exception as e:
        logger.warning("Failed to log tool invocation: %s", e)


def get_recent_audit_logs(limit: int = 100) -> list[dict]:
    """Get recent audit log entries."""
    with get_audit_db() as conn:
        rows = conn.execute(
            """SELECT * FROM tool_invocations
               ORDER BY timestamp DESC
               LIMIT %s""",
            (limit,),
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
               WHERE conversation_id = %s
               ORDER BY timestamp ASC""",
            (conversation_id,),
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
