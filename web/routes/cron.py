"""Cron task management routes."""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from ..cron import discover_cron_tasks, find_task, get_app_runs, get_last_runs, run_cron_task, set_cron_enabled
from ..deps import get_current_user, templates
from ..helpers import format_relative_date
from .html import get_sidebar_data

router = APIRouter()


@router.get("/cron")
def cron_page(request: Request, user_email: str = Depends(get_current_user)):
    """Cron task dashboard — shows all cron-eligible tasks with status."""
    data = get_sidebar_data(user_email)
    tasks = discover_cron_tasks()
    last_runs = get_last_runs(limit_per_app=1)

    for task in tasks:
        runs = last_runs.get(task["slug"], [])
        task["last_run"] = runs[0] if runs else None
        if task["last_run"] and task["last_run"]["started_at"]:
            try:
                dt = datetime.fromisoformat(task["last_run"]["started_at"])
                task["last_run"]["formatted_date"] = format_relative_date(dt)
            except (ValueError, TypeError):
                task["last_run"]["formatted_date"] = task["last_run"]["started_at"]

    return templates.TemplateResponse(
        request,
        "cron.html",
        {
            "section": "cron",
            "tasks": tasks,
            **data,
        },
    )


@router.post("/api/cron/{slug}/run")
def run_task(slug: str):
    """Trigger a manual cron run."""
    task = find_task(slug)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    result = run_cron_task(slug, trigger="manual")
    # Sanitize output to prevent stack trace exposure
    return {
        "slug": result["slug"],
        "status": result["status"],
        "duration_ms": result["duration_ms"],
        "output": result["output"],
    }


@router.post("/api/cron/{slug}/toggle")
async def toggle_task(slug: str, request: Request):
    """Enable or disable a cron task by updating its metadata file."""
    body = await request.body()
    data = (await request.json()) if body else {}
    enabled = data.get("enabled", True)

    if not set_cron_enabled(slug, enabled):
        return JSONResponse({"error": "Task not found"}, status_code=404)

    return {"slug": slug, "enabled": enabled}


@router.get("/api/cron/{slug}/script")
def view_script(slug: str):
    task = find_task(slug)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    return PlainTextResponse(
        Path(task["cron_path"]).read_text(),
        media_type="text/plain; charset=utf-8",
    )


@router.get("/api/cron/{slug}/logs")
def task_logs(slug: str, limit: int = Query(default=20)):
    runs = get_app_runs(slug, limit=limit)
    return runs
