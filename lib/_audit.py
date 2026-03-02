"""
Internal audit logging for API queries.

Requires PostgreSQL via DATABASE_URL.
"""

import json
import logging
import os
from contextlib import contextmanager
from typing import Optional

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

_DATABASE_URL = os.environ.get("DATABASE_URL")

_audit_pool: Optional[ThreadedConnectionPool] = None


def _get_audit_pool() -> ThreadedConnectionPool:
    global _audit_pool
    if _audit_pool is None or _audit_pool.closed:
        _audit_pool = ThreadedConnectionPool(minconn=1, maxconn=3, dsn=_DATABASE_URL)
    return _audit_pool


@contextmanager
def _audit_db():
    """Context manager for audit database connections."""
    pool = _get_audit_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _init_query_log_table():
    """Initialize the query_log table."""
    with _audit_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS query_log (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                source TEXT NOT NULL,
                instance TEXT NOT NULL,
                caller TEXT NOT NULL,
                conversation_id TEXT,
                query_type TEXT,
                query_details TEXT,
                success BOOLEAN NOT NULL,
                error TEXT,
                execution_time_ms INTEGER,
                row_count INTEGER
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_query_log_timestamp ON query_log(timestamp DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_query_log_source_instance ON query_log(source, instance)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_query_log_caller ON query_log(caller)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_query_log_conversation ON query_log(conversation_id)")
        # Purge entries older than 90 days
        cur.execute("DELETE FROM query_log WHERE timestamp < NOW() - INTERVAL '90 days'")


# Initialize on import
try:
    _init_query_log_table()
except Exception as e:
    logger.warning("Failed to initialize query_log table: %s", e)


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
    if conversation_id is None:
        conversation_id = get_conversation_id()

    try:
        with _audit_db() as conn:
            conn.cursor().execute(
                """
                INSERT INTO query_log
                (timestamp, source, instance, caller, conversation_id, query_type,
                 query_details, success, error, execution_time_ms, row_count)
                VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (source, instance, caller, conversation_id, query_type,
                 json.dumps(query_details, default=str),
                 success, error, execution_time_ms, row_count),
            )
    except Exception as e:
        logger.warning("Failed to log query: %s", e)


def get_query_stats(
    since: Optional[str] = None,
    source: Optional[str] = None,
    caller: Optional[str] = None,
) -> dict:
    """Get query statistics from the audit log."""
    with _audit_db() as conn:
        where_clauses = []
        params = []

        if since:
            where_clauses.append("timestamp >= %s")
            params.append(since)
        if source:
            where_clauses.append("source = %s")
            params.append(source)
        if caller:
            where_clauses.append("caller = %s")
            params.append(caller)

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM query_log WHERE {where_sql}", params)
        total = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM query_log WHERE {where_sql} AND success = TRUE", params)
        success_count = cur.fetchone()[0]
        cur.execute(f"SELECT source, COUNT(*) FROM query_log WHERE {where_sql} GROUP BY source", params)
        by_source = dict(cur.fetchall())
        cur.execute(f"SELECT caller, COUNT(*) FROM query_log WHERE {where_sql} GROUP BY caller", params)
        by_caller = dict(cur.fetchall())
        cur.execute(f"SELECT AVG(execution_time_ms) FROM query_log WHERE {where_sql}", params)
        avg_time = cur.fetchone()[0]

        return {
            "total_queries": total,
            "successful_queries": success_count,
            "success_rate": success_count / total if total > 0 else 0,
            "by_source": by_source,
            "by_caller": by_caller,
            "avg_execution_time_ms": int(avg_time) if avg_time else 0,
        }
