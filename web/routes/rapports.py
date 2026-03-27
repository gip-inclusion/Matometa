"""Rapports HTML routes."""

import re

import markdown as md
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from markupsafe import Markup

from ..config import ADMIN_USERS
from ..database import store
from ..deps import get_current_user, templates
from ..interactive_apps import scan_interactive_apps
from .html import get_sidebar_data

router = APIRouter()


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
    return render_rapports_page(request, user_email, report_id=report_id)


def render_report_content(raw_content: str) -> tuple[dict, Markup]:
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


def render_rapports_page(request: Request, user_email: str, report_id: int):
    data = get_sidebar_data(user_email)

    current_report = store.get_report(report_id)
    if not current_report:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    current_report_tags = store.get_report_tags(report_id)
    report_front_matter, report_html = render_report_content(current_report.content)

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
