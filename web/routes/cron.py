"""Cron task management routes."""

from flask import Blueprint, render_template, request, jsonify, abort

from ..cron import discover_cron_tasks, run_cron_task, get_last_runs, get_app_runs, set_cron_enabled
from .. import config
from .html import get_sidebar_data, format_relative_date

bp = Blueprint("cron", __name__)


@bp.route("/cron")
def cron_page():
    """Cron task dashboard — shows all cron-eligible apps with status."""
    data = get_sidebar_data()
    tasks = discover_cron_tasks()
    last_runs = get_last_runs(limit_per_app=1)

    for task in tasks:
        runs = last_runs.get(task["slug"], [])
        task["last_run"] = runs[0] if runs else None
        if task["last_run"] and task["last_run"]["started_at"]:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(task["last_run"]["started_at"])
                task["last_run"]["formatted_date"] = format_relative_date(dt)
            except (ValueError, TypeError):
                task["last_run"]["formatted_date"] = task["last_run"]["started_at"]

    return render_template(
        "cron.html",
        section="cron",
        tasks=tasks,
        **data,
    )


@bp.route("/api/cron/<slug>/run", methods=["POST"])
def run_task(slug):
    """Trigger a manual cron run."""
    # Verify the app exists
    cron_script = config.INTERACTIVE_DIR / slug / "cron.py"
    if not cron_script.exists():
        abort(404)

    result = run_cron_task(slug, trigger="manual")
    return jsonify(result)


@bp.route("/api/cron/<slug>/toggle", methods=["POST"])
def toggle_task(slug):
    """Enable or disable a cron task by updating APP.md."""
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled", True)

    if not set_cron_enabled(slug, enabled):
        abort(404)

    return jsonify({"slug": slug, "enabled": enabled})


@bp.route("/api/cron/<slug>/script")
def view_script(slug):
    """Return the cron.py source code for auditing."""
    cron_script = config.INTERACTIVE_DIR / slug / "cron.py"
    if not cron_script.exists():
        abort(404)

    return cron_script.read_text(), 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.route("/api/cron/<slug>/logs")
def task_logs(slug):
    """Return recent runs for an app as JSON."""
    limit = request.args.get("limit", 20, type=int)
    runs = get_app_runs(slug, limit=limit)
    return jsonify(runs)
