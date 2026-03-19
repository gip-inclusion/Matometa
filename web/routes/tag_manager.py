"""Tag Manager dashboard routes."""

import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from lib._sources import get_matomo, get_tag_manager_sites

from ..deps import get_current_user, templates
from .html import get_sidebar_data

logger = logging.getLogger(__name__)

router = APIRouter()


def _tag_manager_response(
    request: Request, user_email: str, selected_site: int | None = None, selected_trigger: int | None = None
):
    """Render Tag Manager page with optional pre-selection."""
    data = get_sidebar_data(user_email)
    sites = get_tag_manager_sites()
    matomo_url = f"https://{get_matomo().url}"
    return templates.TemplateResponse(
        request,
        "tag_manager.html",
        {
            "section": "tag-manager",
            "sites": sites,
            "selected_site": selected_site,
            "selected_trigger": selected_trigger,
            "matomo_url": matomo_url,
            **data,
        },
    )


@router.get("/tag-manager")
def tag_manager_page(request: Request, user_email: str = Depends(get_current_user)):
    """Tag Manager dashboard — 3-pane audit view."""
    return _tag_manager_response(request, user_email)


@router.get("/tag-manager/{matomo_id}")
def tag_manager_site(request: Request, matomo_id: int, user_email: str = Depends(get_current_user)):
    """Tag Manager with a site pre-selected."""
    return _tag_manager_response(request, user_email, selected_site=matomo_id)


@router.get("/tag-manager/{matomo_id}/{trigger_id}")
def tag_manager_trigger(request: Request, matomo_id: int, trigger_id: int, user_email: str = Depends(get_current_user)):
    """Tag Manager with a site and trigger pre-selected."""
    return _tag_manager_response(request, user_email, selected_site=matomo_id, selected_trigger=trigger_id)


@router.get("/api/tag-manager/sites")
def api_tag_manager_sites():
    """Return configured tag manager sites."""
    return get_tag_manager_sites()


@router.get("/api/tag-manager/site/{matomo_id}")
def api_tag_manager_site(matomo_id: int):
    """Fetch live container data for a site."""
    sites = get_tag_manager_sites()
    site = next((s for s in sites if s["matomo_id"] == matomo_id), None)
    if not site:
        return JSONResponse({"error": "Site not found"}, status_code=404)

    container_id = site["container_id"]

    try:
        start = time.time()
        api = get_matomo()

        # Get container info (draft + releases)
        container = api.get_container(matomo_id, container_id)

        # Find the live version ID
        live_release = next(
            (r for r in container.get("releases", []) if r["environment"] == "live"),
            None,
        )

        if not live_release:
            return {
                "site": site,
                "container": container,
                "triggers": [],
                "tags": [],
                "variables": [],
                "releases": container.get("releases", []),
                "version": None,
                "query_time_ms": int((time.time() - start) * 1000),
            }

        version_id = live_release["idcontainerversion"]

        # Export the live version (triggers, tags, variables)
        export = api.export_version(matomo_id, container_id, version_id)

        triggers = export.get("triggers", [])
        tags = export.get("tags", [])
        variables = export.get("variables", [])

        # Export draft version to get UI-compatible IDs (live IDs are version-specific)
        draft_id = container["draft"]["idcontainerversion"]
        draft = api.export_version(matomo_id, container_id, draft_id)
        draft_trigger_ids = {t["name"]: t["idtrigger"] for t in draft.get("triggers", [])}
        draft_tag_ids = {t["name"]: t["idtag"] for t in draft.get("tags", [])}
        for t in triggers:
            t["draft_id"] = draft_trigger_ids.get(t["name"])
        for t in tags:
            t["draft_id"] = draft_tag_ids.get(t["name"])

        query_time_ms = int((time.time() - start) * 1000)

        return {
            "site": site,
            "container": container,
            "triggers": triggers,
            "tags": tags,
            "variables": variables,
            "releases": container.get("releases", []),
            "version": live_release,
            "query_time_ms": query_time_ms,
        }

    except Exception:
        logger.exception("Tag Manager API error for site %s", int(matomo_id))
        return JSONResponse({"error": "Failed to fetch tag manager data"}, status_code=502)
