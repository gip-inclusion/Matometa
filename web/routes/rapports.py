"""Rapports HTML routes."""

import re
from datetime import datetime

import markdown as md
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from markupsafe import Markup

from .. import config
from ..config import ADMIN_USERS
from ..database import store
from ..deps import get_current_user, templates
from .html import get_sidebar_data

router = APIRouter()


def _parse_app_md(content: str, folder_name: str) -> dict | None:
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
            tags = [t.strip() for t in raw_tags[1:-1].split(",") if t.strip()]
        else:
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


_apps_cache: list[dict] | None = None


def invalidate_apps_cache():
    global _apps_cache
    _apps_cache = None


def scan_interactive_apps():
    """
    Scan /data/interactive/ for valid apps (S3 or local filesystem).

    An app is valid if it has an APP.md file with YAML front-matter.
    Returns list of dicts matching report structure where possible.

    Results are cached and invalidated on write (when sync_to_s3 uploads
    an APP.md file).
    """
    global _apps_cache

    if _apps_cache is not None:
        return _apps_cache

    apps = _scan_interactive_apps_uncached()
    _apps_cache = apps
    return apps


def _scan_interactive_apps_uncached():
    apps = []

    if config.USE_S3:
        from .. import s3

        # List directories in S3
        directories = s3.list_directories()
        for folder_name in directories:
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


@router.get("/rapports")
def rapports(report_id: int | None = Query(default=None, alias="id")):
    """Legacy rapports list — redirects to /rechercher."""
    if report_id is not None:
        return RedirectResponse(f"/rapports/{int(report_id)}", status_code=301)

    return RedirectResponse("/rechercher?show=reports", status_code=301)


@router.get("/rapports/{report_id}.txt")
def rapport_txt(report_id: int):
    report = store.get_report(report_id)
    if not report:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return PlainTextResponse(report.content, media_type="text/plain; charset=utf-8")


@router.get("/rapports/{report_id}")
def rapport_detail(report_id: int, request: Request, user_email: str = Depends(get_current_user)):
    """View a specific report."""
    return _render_rapports_page(request, user_email, report_id=report_id)


def _render_report_content(raw_content: str) -> tuple[dict, Markup]:
    front_matter = {}
    content = raw_content

    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split("\n"):
            idx = line.find(":")
            if idx > 0:
                key = line[:idx].strip().lower()
                value = line[idx + 1 :].strip()
                front_matter[key] = value
        content = content[fm_match.end() :]

    html = md.markdown(content, extensions=["fenced_code", "tables", "toc"])
    html = html.replace("<table>", '<table class="table table-sm table-striped">')

    return front_matter, Markup(html)


def _render_rapports_page(request: Request, user_email: str, report_id: int):
    data = get_sidebar_data(user_email)

    current_report = store.get_report(report_id)
    if not current_report:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    current_report_tags = store.get_report_tags(report_id)
    report_front_matter, report_html = _render_report_content(current_report.content)

    return templates.TemplateResponse(
        request,
        "rapports.html",
        {
            "section": "rapports",
            "current_report": current_report,
            "current_report_tags": current_report_tags,
            "report_front_matter": report_front_matter,
            "report_html": report_html,
            **data,
        },
    )


@router.post("/api/apps/{slug}/pin")
async def pin_app(slug: str, request: Request, user_email: str = Depends(get_current_user)):
    if user_email not in ADMIN_USERS:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    # Verify app exists
    apps = {a["slug"]: a for a in scan_interactive_apps()}
    app = apps.get(slug)
    if not app:
        return JSONResponse({"error": "App not found"}, status_code=404)

    body = await request.body()
    data = (await request.json()) if body else {}
    label = data.get("label", "").strip() or app["title"]
    store.pin_item("app", slug, label)
    return {"ok": True, "label": label}


@router.delete("/api/apps/{slug}/pin")
def unpin_app(slug: str, user_email: str = Depends(get_current_user)):
    if user_email not in ADMIN_USERS:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    store.unpin_item("app", slug)
    return {"ok": True}
