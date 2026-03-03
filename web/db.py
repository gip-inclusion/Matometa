"""Database connection infrastructure (SQLite or PostgreSQL).

Low-level connection management, query helpers, and column validation.
Business logic lives in web/database.py.
"""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Optional, Any

from . import config

logger = logging.getLogger(__name__)

# Database backend detection from DATABASE_URL
USE_POSTGRES = config.DATABASE_URL is not None and config.DATABASE_URL.startswith(("postgres://", "postgresql://"))

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from psycopg2.pool import ThreadedConnectionPool

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
VALID_CONVERSATION_COLUMNS = frozenset({"title", "session_id", "user_id", "status", "pr_url", "updated_at", "pinned_at", "pinned_label", "needs_response", "project_id"})
VALID_REPORT_COLUMNS = frozenset({"title", "website", "category", "tags", "original_query", "content", "updated_at"})


def _build_update_clause(updates: dict, valid_columns: frozenset) -> tuple[str, list]:
    """
    Build a safe UPDATE SET clause from a dict of updates.

    Validates all keys against valid_columns to prevent SQL injection.
    Returns (set_clause, values) for use in parameterized query.
    Uses ? placeholders (ConnectionWrapper converts to %s for PostgreSQL).

    Raises ValueError if any key is not in valid_columns.
    """
    for key in updates:
        if key not in valid_columns:
            raise ValueError(f"Invalid column name: {key}")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    # Convert Python bools to ints for SQLite/PG INTEGER column compatibility
    values = [int(v) if isinstance(v, bool) else v for v in updates.values()]
    return set_clause, values


class DictRowWrapper:
    """Wrapper to make psycopg2 RealDictRow behave like sqlite3.Row for .keys() method."""
    def __init__(self, row: dict):
        self._row = row

    def __getitem__(self, key):
        return self._row[key]

    def keys(self):
        return self._row.keys()


class ConnectionWrapper:
    """Wrapper to normalize sqlite3 and psycopg2 connection interfaces.

    Provides a unified interface for both SQLite and PostgreSQL:
    - Automatic placeholder conversion (? to %s for PostgreSQL)
    - Consistent row factory (dict-like access)
    - Helper methods for common patterns (insert_and_get_id, insert_ignore)
    """

    def __init__(self, conn, is_postgres: bool):
        self._conn = conn
        self._is_postgres = is_postgres
        self._cursor = None

    @property
    def is_postgres(self) -> bool:
        """Check if this is a PostgreSQL connection."""
        return self._is_postgres

    def execute(self, sql: str, params: tuple = ()) -> "ConnectionWrapper":
        """Execute a query, converting placeholders if needed."""
        if self._is_postgres:
            # Convert ? to %s for PostgreSQL
            sql = sql.replace("?", "%s")
            self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        else:
            self._cursor = self._conn.cursor()
        self._cursor.execute(sql, params)
        return self

    def executescript(self, sql: str) -> "ConnectionWrapper":
        """Execute multiple statements (SQLite) or single execution (PostgreSQL)."""
        if self._is_postgres:
            # PostgreSQL can execute multiple statements in one call
            self._cursor = self._conn.cursor()
            self._cursor.execute(sql)
        else:
            self._conn.executescript(sql)
            self._cursor = self._conn.cursor()
        return self

    def executemany(self, sql: str, params_list: list) -> "ConnectionWrapper":
        """Execute a query with multiple parameter sets."""
        if self._is_postgres:
            sql = sql.replace("?", "%s")
            self._cursor = self._conn.cursor()
        else:
            self._cursor = self._conn.cursor()
        self._cursor.executemany(sql, params_list)
        return self

    def fetchone(self) -> Optional[Any]:
        """Fetch one row."""
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._is_postgres:
            return DictRowWrapper(row)
        return row

    def fetchall(self) -> list:
        """Fetch all rows."""
        if self._cursor is None:
            return []
        rows = self._cursor.fetchall()
        if self._is_postgres:
            return [DictRowWrapper(row) for row in rows]
        return rows

    @property
    def lastrowid(self) -> Optional[int]:
        """Get last inserted row ID."""
        if self._cursor is None:
            return None
        if self._is_postgres:
            # PostgreSQL needs RETURNING clause, handle in caller
            return None
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        """Get number of affected rows."""
        if self._cursor is None:
            return 0
        return self._cursor.rowcount

    def insert_and_get_id(self, sql: str, params: tuple = ()) -> Optional[int]:
        """Execute an INSERT and return the new row's ID.

        For PostgreSQL, appends RETURNING id to the query.
        For SQLite, uses lastrowid.
        """
        if self._is_postgres:
            sql = sql.replace("?", "%s")
            if "RETURNING" not in sql.upper():
                sql = sql.rstrip().rstrip(";") + " RETURNING id"
            self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
            self._cursor.execute(sql, params)
            row = self._cursor.fetchone()
            return row["id"] if row else None
        else:
            self._cursor = self._conn.cursor()
            self._cursor.execute(sql, params)
            return self._cursor.lastrowid

    def insert_ignore(self, table: str, columns: list[str], values: tuple) -> "ConnectionWrapper":
        """Execute an INSERT that ignores conflicts (duplicate keys).

        Uses INSERT OR IGNORE for SQLite, INSERT ... ON CONFLICT DO NOTHING for PostgreSQL.
        """
        placeholders = ", ".join(["%s" if self._is_postgres else "?"] * len(values))
        cols = ", ".join(columns)

        if self._is_postgres:
            sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        else:
            sql = f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})"
            self._cursor = self._conn.cursor()

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
    """Get a database connection with row factory."""
    if USE_POSTGRES:
        pool = _get_pg_pool()
        conn = pool.getconn()
        return ConnectionWrapper(conn, is_postgres=True)
    else:
        config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(config.SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-65536")
        conn.execute("PRAGMA foreign_keys = ON")
        return ConnectionWrapper(conn, is_postgres=False)


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        if USE_POSTGRES:
            pool = _get_pg_pool()
            pool.putconn(conn._conn)
        else:
            conn.close()
