"""
Query execution with observability logging.

Usage:
    from lib.query import execute_metabase_query, execute_matomo_query, CallerType

    # Using execute functions (returns QueryResult, never raises)
    result = execute_metabase_query(
        instance="datalake",
        caller=CallerType.AGENT,
        sql="SELECT * FROM table LIMIT 10",
        database_id=2,
    )
    if result.success:
        print(result.data)

    # Using helpers to get configured API clients
    from lib.query import get_metabase, get_matomo

    api = get_metabase(instance='stats')
    result = api.execute_sql("SELECT 1")

    api = get_matomo(instance='inclusion')
    visits = api.get_visits(site_id=117, period="month", date="2025-12-01")
"""

import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from ._sources import get_metabase, get_matomo
from ._audit import log_query, _get_db_connection
from ._pii_guard import check_sql_for_pii

logger = logging.getLogger(__name__)

# Re-export API classes and helpers for convenience
from ._matomo import MatomoAPI, MatomoError
from ._metabase import MetabaseAPI, MetabaseError

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


def execute_metabase_query(
    instance: str,
    caller: CallerType,
    conversation_id: Optional[str] = None,
    sql: Optional[str] = None,
    database_id: Optional[int] = None,
    card_id: Optional[int] = None,
    timeout: int = 60,
) -> QueryResult:
    """
    Execute a Metabase query with logging.

    Either sql+database_id or card_id must be provided.
    Returns QueryResult (never raises).
    """
    # Auto-read conversation_id from environment if not provided
    if conversation_id is None:
        conversation_id = os.environ.get("MATOMETA_CONVERSATION_ID")

    start_time = time.time()

    # PII guard: block queries that select personal data columns
    if sql:
        pii_check = check_sql_for_pii(sql)
        if pii_check.blocked:
            logger.warning("PII guard blocked query: %s", pii_check.reason)
            log_query(
                source="metabase",
                instance=instance,
                caller=caller.value,
                conversation_id=conversation_id,
                query_type="sql",
                query_details={"sql": sql[:500], "pii_blocked": True,
                               "pii_reason": pii_check.reason},
                success=False,
                error=f"PII guard: {pii_check.reason}",
                execution_time_ms=0,
            )
            return QueryResult(
                success=False, data=None,
                error=f"PII guard: {pii_check.reason}",
            )

    try:
        # Get API client (logging is built into the class)
        api = get_metabase(instance, database_id=database_id)
        # Override caller for logging consistency
        api.caller = caller.value

        if sql:
            result = api.execute_sql(sql, timeout=timeout)
            data = {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
            }
        elif card_id is not None:
            result = api.execute_card(card_id, timeout=timeout)
            data = {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
            }
        else:
            raise ValueError("Either sql+database_id or card_id must be provided")

        execution_time_ms = int((time.time() - start_time) * 1000)
        return QueryResult(success=True, data=data, execution_time_ms=execution_time_ms)

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        return QueryResult(success=False, data=None, error=str(e), execution_time_ms=execution_time_ms)


def execute_matomo_query(
    instance: str,
    caller: CallerType,
    conversation_id: Optional[str] = None,
    method: str = "",
    params: Optional[dict] = None,
    timeout: int = 180,
) -> QueryResult:
    """
    Execute a Matomo API query with logging.
    Returns QueryResult (never raises).
    """
    # Auto-read conversation_id from environment if not provided
    if conversation_id is None:
        conversation_id = os.environ.get("MATOMETA_CONVERSATION_ID")

    start_time = time.time()
    params = params or {}

    try:
        # Get API client (logging is built into the class)
        api = get_matomo(instance)
        # Override caller for logging consistency
        api.caller = caller.value

        data = api.request(method, timeout=timeout, **params)

        execution_time_ms = int((time.time() - start_time) * 1000)
        return QueryResult(success=True, data=data, execution_time_ms=execution_time_ms)

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        return QueryResult(success=False, data=None, error=str(e), execution_time_ms=execution_time_ms)


def execute_query(
    source: str,
    instance: str,
    caller: CallerType,
    conversation_id: Optional[str] = None,
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
        conversation_id: ID of the conversation making the request

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
            conversation_id=conversation_id,
            sql=sql,
            database_id=database_id,
            card_id=card_id,
            timeout=timeout,
        )
    elif source == "matomo":
        return execute_matomo_query(
            instance=instance,
            caller=caller,
            conversation_id=conversation_id,
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
