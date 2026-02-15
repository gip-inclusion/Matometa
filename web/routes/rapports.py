"""Rapports HTML routes."""

import re
from datetime import datetime, timedelta
from collections import OrderedDict
from pathlib import Path

import markdown as md
from flask import Blueprint, redirect, render_template, request, url_for, Response, abort
from markupsafe import Markup

from flask import g, jsonify

from ..storage import store
from .html import get_sidebar_data, format_relative_date
from .. import config
from ..config import ADMIN_USERS

bp = Blueprint("rapports", __name__)


def _parse_app_md(content: str, folder_name: str) -> dict | None:
    """Parse APP.md content and return app dict, or None if invalid."""
    if not content.startswith("---"):
        return None

    # Extract front-matter
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    fm = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            fm[key.strip().lower()] = value.strip()

    if "title" not in fm:
        return None

    # Parse updated date
    updated = None
    if "updated" in fm:
        try:
            updated = datetime.strptime(fm["updated"], "%Y-%m-%d")
        except ValueError:
            pass

    # Parse tags (comma-separated or YAML list)
    tags = []
    if "tags" in fm:
        raw_tags = fm["tags"]
        if raw_tags.startswith("[") and raw_tags.endswith("]"):
            # YAML list syntax: [tag1, tag2]
            tags = [t.strip() for t in raw_tags[1:-1].split(",") if t.strip()]
        else:
            # Comma-separated
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

    # Parse authors (comma-separated)
    authors = []
    if "authors" in fm:
        authors = [a.strip() for a in fm["authors"].split(",") if a.strip()]

    return {
        "slug": folder_name,
        "title": fm.get("title"),
        "description": fm.get("description", ""),
        "website": fm.get("website"),
        "category": fm.get("category"),
        "tags": tags,
        "authors": authors,
        "conversation_id": fm.get("conversation_id"),
        "updated": updated,
        "url": f"/interactive/{folder_name}/",
        "is_interactive": True,
    }


def scan_interactive_apps():
    """
    Scan /data/interactive/ for valid apps (S3 or local filesystem).

    An app is valid if it has an APP.md file with YAML front-matter.
    Returns list of dicts matching report structure where possible.
    """
    apps = []

    if config.USE_S3:
        from .. import s3

        # List directories in S3
        directories = s3.list_directories()
        for folder_name in directories:
            # Try to download APP.md
            app_md_content = s3.download_file(f"{folder_name}/APP.md")
            if app_md_content:
                try:
                    content = app_md_content.decode("utf-8")
                    app = _parse_app_md(content, folder_name)
                    if app:
                        apps.append(app)
                except UnicodeDecodeError:
                    continue
    else:
        # Local filesystem
        if not config.INTERACTIVE_DIR.exists():
            return []

        for folder in config.INTERACTIVE_DIR.iterdir():
            if not folder.is_dir():
                continue

            app_md = folder / "APP.md"
            if not app_md.exists():
                continue

            content = app_md.read_text()
            app = _parse_app_md(content, folder.name)
            if app:
                apps.append(app)

    # Sort by updated date (newest first), then by title
    apps.sort(key=lambda a: (a["updated"] or datetime.min, a["title"]), reverse=True)
    return apps


def _group_items_by_date(items):
    """Group report/app items by relative date periods (like conversations)."""
    now = datetime.now()
    today = now.date()

    groups = OrderedDict()
    groups["aujourd'hui"] = []
    groups["hier"] = []
    groups["plus tôt cette semaine"] = []
    groups["la semaine dernière"] = []
    groups["plus tôt ce mois-ci"] = []

    yesterday = today - timedelta(days=1)
    days_since_monday = today.weekday()
    this_week_start = today - timedelta(days=days_since_monday)
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1)
    this_month_start = today.replace(day=1)

    month_names = {
        1: "janvier", 2: "février", 3: "mars", 4: "avril",
        5: "mai", 6: "juin", 7: "juillet", 8: "août",
        9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
    }

    for item in items:
        item_date = item["updated"].date() if item["updated"] else today

        if item_date == today:
            groups["aujourd'hui"].append(item)
        elif item_date == yesterday:
            groups["hier"].append(item)
        elif this_week_start <= item_date < today:
            groups["plus tôt cette semaine"].append(item)
        elif last_week_start <= item_date <= last_week_end:
            groups["la semaine dernière"].append(item)
        elif this_month_start <= item_date < this_week_start:
            groups["plus tôt ce mois-ci"].append(item)
        else:
            month_key = month_names[item_date.month]
            if item_date.year < today.year:
                month_key = f"{month_key} {item_date.year}"
            if month_key not in groups:
                groups[month_key] = []
            groups[month_key].append(item)

    return OrderedDict((k, v) for k, v in groups.items() if v)


@bp.route("/rapports")
def rapports():
    """Rapports section - saved reports browser with optional filtering.

    Legacy ?id= parameter redirects to canonical /rapports/:id URL.
    """
    # Redirect old ?id= URLs to canonical /rapports/:id
    report_id = request.args.get("id", type=int)
    if report_id:
        return redirect(url_for("rapports.rapport_detail", report_id=report_id), code=301)

    return _render_rapports_page()


@bp.route("/rapports/<int:report_id>")
def rapport_detail(report_id: int):
    """View a specific report."""
    return _render_rapports_page(report_id=report_id)


@bp.route("/rapports/<int:report_id>.txt")
def rapport_txt(report_id: int):
    """Return raw markdown content of a report as text/plain."""
    report = store.get_report(report_id)
    if not report:
        abort(404)
    return Response(report.content, mimetype="text/plain; charset=utf-8")


def _render_report_content(raw_content: str) -> tuple[dict, Markup]:
    """Parse YAML front-matter and render markdown to HTML server-side."""
    front_matter = {}
    content = raw_content

    fm_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split('\n'):
            idx = line.find(':')
            if idx > 0:
                key = line[:idx].strip().lower()
                value = line[idx + 1:].strip()
                front_matter[key] = value
        content = content[fm_match.end():]

    html = md.markdown(content, extensions=["fenced_code", "tables", "toc"])
    html = html.replace('<table>', '<table class="table table-sm table-striped">')

    return front_matter, Markup(html)


def _render_rapports_page(report_id: int | None = None):
    """Render the rapports page, optionally showing a specific report."""
    data = get_sidebar_data()

    current_report = None
    current_report_tags = []
    report_front_matter = {}
    report_html = None
    if report_id:
        current_report = store.get_report(report_id)
        if current_report:
            current_report_tags = store.get_report_tags(report_id)
            report_front_matter, report_html = _render_report_content(current_report.content)

    # Filter params
    tag_params = request.args.getlist("tag")
    type_filter = request.args.get("type", "")  # "apps" to show only apps

    # Get reports with tags (only when not viewing a specific report)
    items = []
    if not current_report:
        if type_filter != "apps":
            reports_with_tags = store.list_reports_with_tags(
                tag_names=tag_params if tag_params else None,
                limit=100,
            )
            for report, tags in reports_with_tags:
                report.tag_objects = tags
                items.append({
                    "type": "report",
                    "report": report,
                    "updated": report.updated_at,
                })

        # Get interactive apps and filter by tags if needed
        if type_filter != "reports":
            interactive_apps = scan_interactive_apps()
            for app in interactive_apps:
                # Apps implicitly have type_demande "appli"
                app["type_demande"] = "appli"

                # Check if app matches tag filters
                if tag_params:
                    app_tags = set(app.get("tags", []))
                    app_tags.add(app.get("website", ""))
                    app_tags.add(app.get("category", ""))
                    app_tags.add("appli")  # type_demande

                    # All tag_params must match
                    if not all(t in app_tags for t in tag_params):
                        continue

                items.append({
                    "type": "app",
                    "app": app,
                    "updated": app.get("updated") or datetime.min,
                })

        # Sort combined list by date (newest first)
        items.sort(key=lambda x: x["updated"], reverse=True)

        # Enrich items with formatted dates and icons
        for item in items:
            dt = item["updated"]
            item["formatted_date"] = format_relative_date(dt) if dt and dt != datetime.min else ""
            if item["type"] == "report":
                item["icon"] = "ri-file-text-line"
            else:
                item["icon"] = "ri-window-fill"

        # Group by date
        grouped_items = _group_items_by_date(items)

    # Show all tags used by non-archived reports (stable across filter changes)
    all_tags = store.get_used_report_tags_by_type() if not current_report else {}

    return render_template(
        "rapports.html",
        section="rapports",
        current_report=current_report,
        current_report_tags=current_report_tags,
        report_front_matter=report_front_matter,
        report_html=report_html,
        items=items,
        grouped_items=grouped_items if not current_report else {},
        all_tags=all_tags,
        active_tags=tag_params,
        type_filter=type_filter,
        **data
    )


@bp.route("/api/apps/<slug>/pin", methods=["POST"])
def pin_app(slug: str):
    """Pin an app. Admin only."""
    user_email = getattr(g, "user_email", None)
    if user_email not in ADMIN_USERS:
        return jsonify({"error": "Permission denied"}), 403

    # Verify app exists
    apps = {a["slug"]: a for a in scan_interactive_apps()}
    app = apps.get(slug)
    if not app:
        return jsonify({"error": "App not found"}), 404

    data = request.get_json() or {}
    label = data.get("label", "").strip() or app["title"]
    store.pin_item("app", slug, label)
    return jsonify({"ok": True, "label": label}), 200


@bp.route("/api/apps/<slug>/pin", methods=["DELETE"])
def unpin_app(slug: str):
    """Unpin an app. Admin only."""
    user_email = getattr(g, "user_email", None)
    if user_email not in ADMIN_USERS:
        return jsonify({"error": "Permission denied"}), 403

    store.unpin_item("app", slug)
    return jsonify({"ok": True}), 200
