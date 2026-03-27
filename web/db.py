"""Database connection infrastructure (PostgreSQL).

Low-level connection management, query helpers, and column validation.
Business logic lives in web/database.py.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from . import config

logger = logging.getLogger(__name__)

pg_pool: Optional[ThreadedConnectionPool] = None


def get_pg_pool() -> ThreadedConnectionPool:
    global pg_pool
    if pg_pool is None or pg_pool.closed:
        pg_pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=config.DATABASE_URL,
        )
        logger.info("PostgreSQL connection pool created (max=10)")
    return pg_pool


# Valid column names for dynamic updates (security: prevents SQL injection)
VALID_CONVERSATION_COLUMNS = frozenset(
    {"title", "session_id", "user_id", "status", "pr_url", "updated_at", "pinned_at", "pinned_label", "needs_response"}
)
VALID_REPORT_COLUMNS = frozenset({"title", "website", "category", "tags", "original_query", "content", "updated_at"})


def build_update_clause(updates: dict, valid_columns: frozenset) -> tuple[str, list]:
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
        self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        self._cursor.execute(sql, params)
        return self

    def execute_raw(self, sql: str) -> "ConnectionWrapper":
        self._cursor = self._conn.cursor()
        self._cursor.execute(sql)
        return self

    def executemany(self, sql: str, params_list: list) -> "ConnectionWrapper":
        self._cursor = self._conn.cursor()
        self._cursor.executemany(sql, params_list)
        return self

    def fetchone(self) -> Optional[Any]:
        if self._cursor is None:
            return None
        return self._cursor.fetchone()

    def fetchall(self) -> list:
        if self._cursor is None:
            return []
        return self._cursor.fetchall()

    @property
    def rowcount(self) -> int:
        if self._cursor is None:
            return 0
        return self._cursor.rowcount

    def insert_and_get_id(self, sql: str, params: tuple = ()) -> Optional[int]:
        if "RETURNING" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        self._cursor.execute(sql, params)
        row = self._cursor.fetchone()
        return row["id"] if row else None

    def insert_ignore(self, table: str, columns: list[str], values: tuple) -> "ConnectionWrapper":
        placeholders = ", ".join(["%s"] * len(values))
        cols = ", ".join(columns)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        self._cursor.execute(sql, values)
        return self

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_connection() -> ConnectionWrapper:
    pool = get_pg_pool()
    conn = pool.getconn()
    return ConnectionWrapper(conn)


test_conn_var: ContextVar[Optional[ConnectionWrapper]] = ContextVar("db_test_conn", default=None)


@contextmanager
def test_transaction():
    """Hold one pooled connection for a test; all ``get_db()`` calls share it and do not commit.

    Rolls back on exit so tests leave no durable DB state. Used by pytest fixtures.
    """
    conn = get_connection()
    token = test_conn_var.set(conn)
    conn.rollback()
    try:
        yield
    finally:
        try:
            conn.rollback()
        finally:
            test_conn_var.reset(token)
            pool = get_pg_pool()
            pool.putconn(conn._conn)


@contextmanager
def get_db():
    """Context manager for database connections."""
    test_conn = test_conn_var.get()
    if test_conn is not None:
        yield test_conn
        return
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool = get_pg_pool()
        pool.putconn(conn._conn)
