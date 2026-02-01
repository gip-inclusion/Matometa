"""
Internal audit logging for queries.

This module handles logging to the audit database.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Use the same audit database as web/audit.py
AUDIT_DB_PATH = Path(__file__).parent.parent / "data" / "audit.db"

logger = logging.getLogger(__name__)


def _get_db_connection() -> sqlite3.Connection:
    """Get audit database connection."""
    AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUDIT_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")
    return conn


def _init_query_log_table():
    """Initialize the query_log table in audit.db."""
    conn = _get_db_connection()

    # Check if table exists and has old schema (user_email instead of conversation_id)
    cursor = conn.execute("PRAGMA table_info(query_log)")
    columns = {row[1] for row in cursor.fetchall()}

    if "user_email" in columns and "conversation_id" not in columns:
        # Migrate: rename user_email to conversation_id
        conn.executescript("""
            ALTER TABLE query_log RENAME COLUMN user_email TO conversation_id;
            CREATE INDEX IF NOT EXISTS idx_query_log_conversation
                ON query_log(conversation_id);
        """)
    elif not columns:
        # Create new table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS query_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                instance TEXT NOT NULL,
                caller TEXT NOT NULL,
                conversation_id TEXT,
                query_type TEXT,
                query_details TEXT,
                success INTEGER NOT NULL,
                error TEXT,
                execution_time_ms INTEGER,
                row_count INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_query_log_timestamp
                ON query_log(timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_query_log_source_instance
                ON query_log(source, instance);

            CREATE INDEX IF NOT EXISTS idx_query_log_caller
                ON query_log(caller);

            CREATE INDEX IF NOT EXISTS idx_query_log_conversation
                ON query_log(conversation_id);
        """)

    conn.commit()
    conn.close()


# Initialize on import
_init_query_log_table()


def get_conversation_id() -> Optional[str]:
    """Get conversation_id from environment."""
    return os.environ.get("MATOMETA_CONVERSATION_ID")


def log_query(
    source: str,
    instance: str,
    caller: str,
    conversation_id: Optional[str],
    query_type: str,
    query_details: dict,
    success: bool,
    error: Optional[str],
    execution_time_ms: int,
    row_count: Optional[int] = None,
):
    """Log a query execution to the audit database."""
    # Auto-read conversation_id from environment if not provided
    if conversation_id is None:
        conversation_id = get_conversation_id()

    try:
        conn = _get_db_connection()
        conn.execute(
            """
            INSERT INTO query_log
            (timestamp, source, instance, caller, conversation_id, query_type,
             query_details, success, error, execution_time_ms, row_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                source,
                instance,
                caller,
                conversation_id,
                query_type,
                json.dumps(query_details, default=str),
                1 if success else 0,
                error,
                execution_time_ms,
                row_count,
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to log query: {e}")
