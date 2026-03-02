"""Database connection infrastructure (PostgreSQL).

Low-level connection management, query helpers, and column validation.
Business logic lives in web/database.py.
"""

import logging
from contextlib import contextmanager
from typing import Optional, Any

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from . import config

logger = logging.getLogger(__name__)

_pg_pool: Optional[ThreadedConnectionPool] = None


def _get_pg_pool() -> ThreadedConnectionPool:
    global _pg_pool
    if _pg_pool is None or _pg_pool.closed:
        _pg_pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=config.DATABASE_URL,
        )
        logger.info("PostgreSQL connection pool created (max=10)")
    return _pg_pool


# Valid column names for dynamic updates (security: prevents SQL injection)
VALID_CONVERSATION_COLUMNS = frozenset({"title", "session_id", "user_id", "status", "pr_url", "updated_at", "pinned_at", "pinned_label", "needs_response"})
VALID_REPORT_COLUMNS = frozenset({"title", "website", "category", "tags", "original_query", "content", "updated_at"})


def _build_update_clause(updates: dict, valid_columns: frozenset) -> tuple[str, list]:
    """
    Build a safe UPDATE SET clause from a dict of updates.

    Validates all keys against valid_columns to prevent SQL injection.
    Returns (set_clause, values) for use in parameterized query.

    Raises ValueError if any key is not in valid_columns.
    """
    for key in updates:
        if key not in valid_columns:
            raise ValueError(f"Invalid column name: {key}")

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = [int(v) if isinstance(v, bool) else v for v in updates.values()]
    return set_clause, values


class ConnectionWrapper:
    """Wrapper around psycopg2 connections.

    Provides helper methods for common patterns (insert_and_get_id, insert_ignore).
    All SQL must use %s placeholders (native psycopg2 format).
    """

    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, sql: str, params: tuple = ()) -> "ConnectionWrapper":
        """Execute a query with %s placeholders."""
        self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        self._cursor.execute(sql, params)
        return self

    def execute_raw(self, sql: str) -> "ConnectionWrapper":
        """Execute raw SQL (multi-statement, no parameters, no dict cursor)."""
        self._cursor = self._conn.cursor()
        self._cursor.execute(sql)
        return self

    def executemany(self, sql: str, params_list: list) -> "ConnectionWrapper":
        """Execute a query with multiple parameter sets."""
        self._cursor = self._conn.cursor()
        self._cursor.executemany(sql, params_list)
        return self

    def fetchone(self) -> Optional[Any]:
        """Fetch one row as a dict (via RealDictCursor)."""
        if self._cursor is None:
            return None
        return self._cursor.fetchone()

    def fetchall(self) -> list:
        """Fetch all rows as dicts (via RealDictCursor)."""
        if self._cursor is None:
            return []
        return self._cursor.fetchall()

    @property
    def rowcount(self) -> int:
        """Get number of affected rows."""
        if self._cursor is None:
            return 0
        return self._cursor.rowcount

    def insert_and_get_id(self, sql: str, params: tuple = ()) -> Optional[int]:
        """Execute an INSERT and return the new row's ID via RETURNING."""
        if "RETURNING" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        self._cursor.execute(sql, params)
        row = self._cursor.fetchone()
        return row["id"] if row else None

    def insert_ignore(self, table: str, columns: list[str], values: tuple) -> "ConnectionWrapper":
        """Execute an INSERT ... ON CONFLICT DO NOTHING."""
        placeholders = ", ".join(["%s"] * len(values))
        cols = ", ".join(columns)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        self._cursor.execute(sql, values)
        return self

    def commit(self):
        """Commit the transaction."""
        self._conn.commit()

    def rollback(self):
        """Rollback the transaction."""
        self._conn.rollback()

    def close(self):
        """Close the connection."""
        self._conn.close()


def get_connection() -> ConnectionWrapper:
    """Get a database connection from the pool."""
    pool = _get_pg_pool()
    conn = pool.getconn()
    return ConnectionWrapper(conn)


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool = _get_pg_pool()
        pool.putconn(conn._conn)
