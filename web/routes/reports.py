"""Reports API routes."""

import json
import logging
import urllib.error

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from .. import notion
from ..config import ADMIN_USERS
from ..deps import get_current_user
from ..storage import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports")


@router.get("/tags")
def list_tags(type: str | None = Query(default=None, alias="type")):
    if type:
        tags = store.get_all_tags(tag_type=type)
    else:
        tags = store.get_all_tags()

    return {"tags": [{"name": t.name, "type": t.type, "label": t.label} for t in tags]}


@router.get("")
def list_reports(
    website: str | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(default=50),
):
    reports = store.list_reports(website=website, category=category, limit=limit)
    return {
        "reports": [
            {
                "id": r.id,
                "title": r.title,
                "website": r.website,
                "category": r.category,
                "conversation_id": r.conversation_id,
                "version": r.version,
                "updated_at": r.updated_at.isoformat(),
                "links": {
                    "self": f"/api/reports/{r.id}",
                    "conversation": f"/api/conversations/{r.conversation_id}",
                },
            }
            for r in reports
        ]
    }


@router.get("/{report_id}")
def get_report(report_id: int):
    report = store.get_report(report_id)
    if not report:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    return {
        "id": report.id,
        "title": report.title,
        "website": report.website,
        "category": report.category,
        "tags": report.tags,
        "original_query": report.original_query,
        "version": report.version,
        "content": report.content,
        "source_conversation_id": report.source_conversation_id,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
        "links": {
            "self": f"/api/reports/{report.id}",
            "view": f"/rapports/{report.id}",
        },
    }


@router.delete("/{report_id}")
def delete_report(report_id: int):
    if store.delete_report(report_id):
        return Response(status_code=200)
    return JSONResponse({"error": "Report not found"}, status_code=404)


@router.post("/{report_id}/archive")
def archive_report(report_id: int):
    if store.archive_report(report_id):
        return Response(status_code=200)
    return JSONResponse({"error": "Report not found"}, status_code=404)


@router.post("")
async def create_report(request: Request, user_email: str = Depends(get_current_user)):
    data = await request.json()
    if not data or "title" not in data or "content" not in data:
        return JSONResponse({"error": "Missing title or content"}, status_code=400)

    report = store.create_report(
        title=data["title"],
        content=data["content"],
        website=data.get("website"),
        category=data.get("category"),
        tags=data.get("tags"),
        original_query=data.get("original_query"),
        source_conversation_id=data.get("source_conversation_id"),
        user_id=user_email,
    )

    if not report:
        return JSONResponse({"error": "Failed to create report"}, status_code=500)

    # Set tags in the new-style join table
    if data.get("tags"):
        store.set_report_tags(report.id, data["tags"], update_timestamp=False)

    # Optionally add link message to source conversation
    if data.get("source_conversation_id"):
        store.add_message(
            data["source_conversation_id"], "report", json.dumps({"report_id": report.id, "title": report.title})
        )

    return JSONResponse(
        {
            "id": report.id,
            "title": report.title,
            "links": {
                "self": f"/api/reports/{report.id}",
                "view": f"/rapports/{report.id}",
            },
        },
        status_code=201,
    )


@router.post("/{report_id}/publish-notion")
def publish_to_notion(report_id: int):
    """Publish a report to Notion. Returns the Notion page URL."""
    if not notion.is_configured():
        return JSONResponse({"error": "Notion not configured"}, status_code=503)

    report = store.get_report(report_id)
    if not report:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    if report.notion_url:
        return {"url": report.notion_url}

    try:
        _page_id, url = notion.publish_report(
            title=report.title,
            content=report.content,
            website=report.website,
            original_query=report.original_query,
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")[:200]
        logger.error("Notion API error %d: %s", e.code, body)
        return JSONResponse({"error": "Notion API error"}, status_code=502)
    except Exception:
        logger.exception("Notion publish failed")
        return JSONResponse({"error": "Failed to publish to Notion"}, status_code=500)

    # Store the URL
    from ..database import get_db

    with get_db() as conn:
        conn.execute("UPDATE reports SET notion_url = %s WHERE id = %s", (url, report_id))

    return {"url": url}


@router.post("/{report_id}/pin")
async def pin_report(report_id: int, request: Request, user_email: str = Depends(get_current_user)):
    if user_email not in ADMIN_USERS:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    report = store.get_report(report_id)
    if not report:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    body = await request.body()
    data = (await request.json()) if body else {}
    label = data.get("label", "").strip() or report.title
    store.pin_item("report", str(report_id), label)
    return {"ok": True, "label": label}


@router.delete("/{report_id}/pin")
def unpin_report(report_id: int, user_email: str = Depends(get_current_user)):
    if user_email not in ADMIN_USERS:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    store.unpin_item("report", str(report_id))
    return {"ok": True}


@router.get("/{report_id}/tags")
def get_report_tags(report_id: int):
    tags = store.get_report_tags(report_id)
    return {"tags": [{"name": t.name, "type": t.type, "label": t.label} for t in tags]}


@router.put("/{report_id}/tags")
async def set_report_tags(report_id: int, request: Request):
    data = await request.json()
    if not data or "tags" not in data:
        return JSONResponse({"error": "Missing 'tags' field"}, status_code=400)

    tag_names = data["tags"]
    if not isinstance(tag_names, list):
        return JSONResponse({"error": "'tags' must be a list"}, status_code=400)

    store.set_report_tags(report_id, tag_names)
    tags = store.get_report_tags(report_id)
    return {"tags": [{"name": t.name, "type": t.type, "label": t.label} for t in tags]}
