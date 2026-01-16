"""
Query execution with observability logging.

Usage:
    from lib.query import execute_query, CallerType

    # From an app (frontend)
    result = execute_query(
        source="metabase",
        instance="datalake",
        caller=CallerType.APP,
        user_email="user@example.com",
        sql="SELECT * FROM table LIMIT 10",
        database_id=2,
    )

    # From the agent
    result = execute_query(
        source="matomo",
        instance="inclusion",
        caller=CallerType.AGENT,
        user_email="user@example.com",
        method="VisitsSummary.get",
        params={"idSite": 117, "period": "month", "date": "2025-12-01"},
    )
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .sources import get_metabase, get_matomo

# Use the same audit database as web/audit.py
AUDIT_DB_PATH = Path(__file__).parent.parent / "data" / "audit.db"

logger = logging.getLogger(__name__)


class CallerType(str, Enum):
    """Type of caller making the query."""
    AGENT = "agent"
    APP = "app"


@dataclass
class QueryResult:
    """Result of a query execution."""
    success: bool
    data: Any
    error: Optional[str] = None
    execution_time_ms: int = 0


def _get_db_connection() -> sqlite3.Connection:
    """Get audit database connection."""
    AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUDIT_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_query_log_table():
    """Initialize the query_log table in audit.db."""
    conn = _get_db_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            source TEXT NOT NULL,
            instance TEXT NOT NULL,
            caller TEXT NOT NULL,
            user_email TEXT,
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
    """)
    conn.commit()
    conn.close()


# Initialize on import
_init_query_log_table()


def _log_query(
    source: str,
    instance: str,
    caller: CallerType,
    user_email: Optional[str],
    query_type: str,
    query_details: dict,
    success: bool,
    error: Optional[str],
    execution_time_ms: int,
    row_count: Optional[int] = None,
):
    """Log a query execution to the audit database."""
    try:
        conn = _get_db_connection()
        conn.execute(
            """
            INSERT INTO query_log
            (timestamp, source, instance, caller, user_email, query_type,
             query_details, success, error, execution_time_ms, row_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                source,
                instance,
                caller.value,
                user_email,
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


def execute_metabase_query(
    instance: str,
    caller: CallerType,
    user_email: Optional[str] = None,
    sql: Optional[str] = None,
    database_id: Optional[int] = None,
    card_id: Optional[int] = None,
    timeout: int = 60,
) -> QueryResult:
    """
    Execute a Metabase query with logging.

    Either sql+database_id or card_id must be provided.
    """
    start_time = time.time()
    query_type = "sql" if sql else "card"
    query_details = {
        "sql": sql[:500] if sql else None,  # Truncate for logging
        "database_id": database_id,
        "card_id": card_id,
    }

    try:
        api = get_metabase(instance, database_id=database_id)

        if sql and database_id is not None:
            result = api.execute_sql(sql, timeout=timeout)
            data = {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
            }
            row_count = result.row_count
        elif card_id is not None:
            result = api.execute_card(card_id, timeout=timeout)
            data = {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
            }
            row_count = result.row_count
        else:
            raise ValueError("Either sql+database_id or card_id must be provided")

        execution_time_ms = int((time.time() - start_time) * 1000)

        _log_query(
            source="metabase",
            instance=instance,
            caller=caller,
            user_email=user_email,
            query_type=query_type,
            query_details=query_details,
            success=True,
            error=None,
            execution_time_ms=execution_time_ms,
            row_count=row_count,
        )

        return QueryResult(success=True, data=data, execution_time_ms=execution_time_ms)

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        error_msg = str(e)

        _log_query(
            source="metabase",
            instance=instance,
            caller=caller,
            user_email=user_email,
            query_type=query_type,
            query_details=query_details,
            success=False,
            error=error_msg,
            execution_time_ms=execution_time_ms,
        )

        return QueryResult(success=False, data=None, error=error_msg, execution_time_ms=execution_time_ms)


def execute_matomo_query(
    instance: str,
    caller: CallerType,
    user_email: Optional[str] = None,
    method: str = "",
    params: Optional[dict] = None,
    timeout: int = 180,
) -> QueryResult:
    """
    Execute a Matomo API query with logging.
    """
    start_time = time.time()
    params = params or {}
    query_details = {
        "method": method,
        "params": params,
    }

    try:
        api = get_matomo(instance)
        data = api.request(method, timeout=timeout, **params)

        # Estimate row count for list responses
        row_count = len(data) if isinstance(data, list) else None

        execution_time_ms = int((time.time() - start_time) * 1000)

        _log_query(
            source="matomo",
            instance=instance,
            caller=caller,
            user_email=user_email,
            query_type=method,
            query_details=query_details,
            success=True,
            error=None,
            execution_time_ms=execution_time_ms,
            row_count=row_count,
        )

        return QueryResult(success=True, data=data, execution_time_ms=execution_time_ms)

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        error_msg = str(e)

        _log_query(
            source="matomo",
            instance=instance,
            caller=caller,
            user_email=user_email,
            query_type=method,
            query_details=query_details,
            success=False,
            error=error_msg,
            execution_time_ms=execution_time_ms,
        )

        return QueryResult(success=False, data=None, error=error_msg, execution_time_ms=execution_time_ms)


def execute_query(
    source: str,
    instance: str,
    caller: CallerType,
    user_email: Optional[str] = None,
    # Metabase params
    sql: Optional[str] = None,
    database_id: Optional[int] = None,
    card_id: Optional[int] = None,
    # Matomo params
    method: Optional[str] = None,
    params: Optional[dict] = None,
    # Common
    timeout: int = 60,
) -> QueryResult:
    """
    Execute a query against Metabase or Matomo with logging.

    Args:
        source: "metabase" or "matomo"
        instance: Instance name (e.g., "stats", "datalake", "inclusion")
        caller: CallerType.AGENT or CallerType.APP
        user_email: Email of the user making the request

        # For Metabase:
        sql: SQL query string
        database_id: Metabase database ID
        card_id: Metabase card/question ID (alternative to sql)

        # For Matomo:
        method: Matomo API method (e.g., "VisitsSummary.get")
        params: Matomo API parameters

        timeout: Request timeout in seconds

    Returns:
        QueryResult with success status, data, and timing info
    """
    if source == "metabase":
        return execute_metabase_query(
            instance=instance,
            caller=caller,
            user_email=user_email,
            sql=sql,
            database_id=database_id,
            card_id=card_id,
            timeout=timeout,
        )
    elif source == "matomo":
        return execute_matomo_query(
            instance=instance,
            caller=caller,
            user_email=user_email,
            method=method or "",
            params=params,
            timeout=timeout,
        )
    else:
        return QueryResult(
            success=False,
            data=None,
            error=f"Unknown source: {source}. Use 'metabase' or 'matomo'.",
        )


def get_query_stats(
    since: Optional[str] = None,
    source: Optional[str] = None,
    caller: Optional[str] = None,
) -> dict:
    """
    Get query statistics from the log.

    Args:
        since: ISO timestamp to filter from (e.g., "2025-01-01")
        source: Filter by source ("metabase" or "matomo")
        caller: Filter by caller type ("agent" or "app")

    Returns:
        Dict with statistics
    """
    conn = _get_db_connection()

    where_clauses = []
    params = []

    if since:
        where_clauses.append("timestamp >= ?")
        params.append(since)
    if source:
        where_clauses.append("source = ?")
        params.append(source)
    if caller:
        where_clauses.append("caller = ?")
        params.append(caller)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Total queries
    total = conn.execute(
        f"SELECT COUNT(*) FROM query_log WHERE {where_sql}", params
    ).fetchone()[0]

    # Success rate
    success = conn.execute(
        f"SELECT COUNT(*) FROM query_log WHERE {where_sql} AND success = 1", params
    ).fetchone()[0]

    # By source
    by_source = dict(conn.execute(
        f"SELECT source, COUNT(*) FROM query_log WHERE {where_sql} GROUP BY source", params
    ).fetchall())

    # By caller
    by_caller = dict(conn.execute(
        f"SELECT caller, COUNT(*) FROM query_log WHERE {where_sql} GROUP BY caller", params
    ).fetchall())

    # Avg execution time
    avg_time = conn.execute(
        f"SELECT AVG(execution_time_ms) FROM query_log WHERE {where_sql}", params
    ).fetchone()[0]

    conn.close()

    return {
        "total_queries": total,
        "successful_queries": success,
        "success_rate": success / total if total > 0 else 0,
        "by_source": by_source,
        "by_caller": by_caller,
        "avg_execution_time_ms": int(avg_time) if avg_time else 0,
    }
