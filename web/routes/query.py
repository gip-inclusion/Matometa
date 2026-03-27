"""Query API endpoint for frontend apps.

Provides CORS-protected access to Metabase and Matomo queries
for static HTML/JS apps served from /interactive.
"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from lib.query import CallerType, execute_query

router = APIRouter(prefix="/api")

# Allowed origins for CORS
ALLOWED_ORIGINS = {
    "https://matometa.osc-fr1.scalingo.io",
    "https://matometa.inclusion.gouv.fr",
    "https://matometa.ljt.cc",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
}


def cors_headers(origin: str | None) -> dict:
    headers = {}
    if origin in ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        headers["Access-Control-Allow-Headers"] = "Content-Type"
        headers["Access-Control-Allow-Credentials"] = "true"
    return headers


@router.api_route("/query", methods=["POST", "OPTIONS"])
async def query(request: Request):
    """
    Execute a query against Metabase or Matomo.

    Request body (JSON):
        source: "metabase" or "matomo"
        instance: Instance name (e.g., "stats", "datalake", "inclusion")

        # For Metabase:
        sql: SQL query string (with database_id)
        database_id: Metabase database ID
        card_id: Metabase card/question ID (alternative to sql)

        # For Matomo:
        method: Matomo API method (e.g., "VisitsSummary.get")
        params: Matomo API parameters dict

        # Optional:
        timeout: Request timeout in seconds (default 60)

    Returns:
        JSON with success, data, error, execution_time_ms
    """
    origin = request.headers.get("Origin")
    cors = cors_headers(origin)

    # Handle preflight
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=cors)

    # Check origin
    if origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"error": "Origin not allowed"}, status_code=403, headers=cors)

    try:
        data = await request.json()
    except Exception:
        data = None

    if not data:
        return JSONResponse({"error": "JSON body required"}, status_code=400, headers=cors)

    source = data.get("source")
    instance = data.get("instance")

    if not source or not instance:
        return JSONResponse({"error": "source and instance are required"}, status_code=400, headers=cors)

    # execute_query is synchronous — run in threadpool
    result = await asyncio.to_thread(
        execute_query,
        source=source,
        instance=instance,
        caller=CallerType.APP,
        sql=data.get("sql"),
        database_id=data.get("database_id"),
        card_id=data.get("card_id"),
        method=data.get("method"),
        params=data.get("params"),
        timeout=data.get("timeout", 60),
    )

    response = {
        "success": result.success,
        "data": result.data,
        "error": result.error,
        "execution_time_ms": result.execution_time_ms,
    }

    status = 200 if result.success else 500
    return JSONResponse(response, status_code=status, headers=cors)
