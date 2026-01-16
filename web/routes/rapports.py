"""Rapports HTML routes."""

from datetime import datetime
from pathlib import Path

from flask import Blueprint, render_template, request

from ..storage import store
from .html import get_sidebar_data
from .. import config

bp = Blueprint("rapports", __name__)


def scan_interactive_apps():
    """
    Scan /data/interactive/ for valid apps.

    An app is valid if it has an APP.md file with YAML front-matter.
    Returns list of dicts matching report structure where possible.
    """
    interactive_dir = config.BASE_DIR / "data" / "interactive"
    if not interactive_dir.exists():
        return []

    apps = []
    for folder in interactive_dir.iterdir():
        if not folder.is_dir():
            continue

        app_md = folder / "APP.md"
        if not app_md.exists():
            continue

        # Parse front-matter
        content = app_md.read_text()
        if not content.startswith("---"):
            continue

        # Extract front-matter
        parts = content.split("---", 2)
        if len(parts) < 3:
            continue

        fm = {}
        for line in parts[1].strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                fm[key.strip().lower()] = value.strip()

        if "title" not in fm:
            continue

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

        apps.append({
            "slug": folder.name,
            "title": fm.get("title"),
            "description": fm.get("description", ""),
            "website": fm.get("website"),
            "category": fm.get("category"),
            "tags": tags,
            "authors": authors,
            "conversation_id": fm.get("conversation_id"),
            "updated": updated,
            "url": f"/interactive/{folder.name}/",
            "is_interactive": True,
        })

    # Sort by updated date (newest first), then by title
    apps.sort(key=lambda a: (a["updated"] or datetime.min, a["title"]), reverse=True)
    return apps


@bp.route("/rapports")
def rapports():
    """Rapports section - saved reports browser with optional filtering."""
    data = get_sidebar_data()
    report_id = request.args.get("id", type=int)

    current_report = None
    current_report_tags = []
    if report_id:
        current_report = store.get_report(report_id)
        if current_report:
            current_report_tags = store.get_report_tags(report_id)

    # Filter params
    tag_params = request.args.getlist("tag")

    # Get reports with tags (only when not viewing a specific report)
    items = []
    if not current_report:
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

    # Get only tags that are actually used by reports + add "appli" for apps
    all_tags = store.get_used_report_tags_by_type()
    # Ensure "appli" type is available if we have apps
    if not current_report:
        appli_tag = store.get_tag_by_name("appli")
        if appli_tag:
            if "type_demande" not in all_tags:
                all_tags["type_demande"] = []
            if appli_tag not in all_tags["type_demande"]:
                all_tags["type_demande"].append(appli_tag)

    return render_template(
        "rapports.html",
        section="rapports",
        current_report=current_report,
        current_report_tags=current_report_tags,
        items=items,
        all_tags=all_tags,
        active_tags=tag_params,
        **data
    )
