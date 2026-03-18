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

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from ._matomo import MatomoAPI, MatomoError  # noqa: F401 — re-exported
from ._metabase import MetabaseAPI, MetabaseError  # noqa: F401 — re-exported

# Re-export API classes and helpers for convenience
from ._sources import get_matomo, get_metabase


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
