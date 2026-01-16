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
    """Rapports section - saved reports browser."""
    data = get_sidebar_data()
    report_id = request.args.get("id", type=int)

    current_report = None
    if report_id:
        current_report = store.get_report(report_id)

    reports = store.list_reports(limit=50) if not current_report else []
    interactive_apps = scan_interactive_apps() if not current_report else []

    return render_template(
        "rapports.html",
        section="rapports",
        current_report=current_report,
        reports=reports,
        interactive_apps=interactive_apps,
        **data
    )
