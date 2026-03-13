"""HTML page routes."""

import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse

from ..config import ADMIN_USERS, DISPLAY_TIMEZONE, FEATURE_KNOWLEDGE_CHAT
from ..deps import get_current_user, templates
from ..helpers import (
    _validate_conv_id,
    list_knowledge_files,
    list_knowledge_sections,
    list_staged_files,
    validate_knowledge_path,
)
from ..storage import store
from .research import find_similar_pages, get_corpus_stats, get_page, search_corpus

logger = logging.getLogger(__name__)

router = APIRouter()


def humanize_title(title: str) -> str:
    """Clean up a title: strip date prefix, ISO timestamps, separators; capitalize."""
    if not title:
        return title
    title = re.sub(r"^\d{4}-\d{2}(-\d{2})?[-_]?", "", title)
    title = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?", "", title)
    title = re.sub(r"[-_]+", " ", title)
    if title:
        title = title[0].upper() + title[1:]
    return title.strip()


DISPLAY_TZ = ZoneInfo(DISPLAY_TIMEZONE)


def _now_local():
    """Current time in the display timezone (mockable for tests)."""
    return datetime.now(DISPLAY_TZ)


def _to_local(dt):
    """Convert a naive-UTC datetime to the display timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(DISPLAY_TZ)


def format_relative_date(dt):
    """Format a datetime as a relative date string in Europe/Paris timezone.

    - If today: just time -> "14:32"
    - If yesterday: -> "hier, 12:45"
    - If this week (not today/yesterday): -> "mercredi 11:11"
    - If older: -> "23/01/2026 a 22:00"
    """
    now = _now_local()
    dt = _to_local(dt)
    today = now.date()
    dt_date = dt.date()

    day_names = {0: "lundi", 1: "mardi", 2: "mercredi", 3: "jeudi", 4: "vendredi", 5: "samedi", 6: "dimanche"}

    # Calculate start of this week (Monday)
    days_since_monday = today.weekday()
    this_week_start = today - timedelta(days=days_since_monday)

    if dt_date == today:
        return dt.strftime("%H:%M")
    elif dt_date == today - timedelta(days=1):
        return f"hier, {dt.strftime('%H:%M')}"
    elif this_week_start <= dt_date < today:
        day_name = day_names[dt_date.weekday()]
        return f"{day_name} {dt.strftime('%H:%M')}"
    else:
        return dt.strftime("%d/%m/%Y à %H:%M")


def get_sidebar_data(user_email: str | None):
    """Get data for sidebar (recent conversations for current user)."""
    conversations = store.list_conversations(limit=20, user_id=user_email)

    # Batch fetch tags for all conversations (1 query instead of 20)
    conv_ids = [conv.id for conv in conversations]
    tags_batch = store.get_conversation_tags_batch(conv_ids)

    running_ids = []
    for conv in conversations:
        if conv.title:
            conv.title = humanize_title(conv.title)
        conv.is_running = conv.needs_response
        if conv.is_running:
            running_ids.append(conv.id)

        # Determine icon from tags
        tags = tags_batch.get(conv.id, [])
        conv.icon = "ri-chat-3-fill"  # Default
        for tag in tags:
            if tag.name == "extraction":
                conv.icon = "ri-table-fill"
                break
            elif tag.name == "meta":
                conv.icon = "ri-settings-3-fill"
                break
            elif tag.name == "appli":
                conv.icon = "ri-window-fill"
                break
            elif tag.name == "analyse":
                conv.icon = "ri-chat-3-fill"
                break

    # Pinned conversations (global, visible to all users)
    pinned_conversations = store.list_pinned_conversations()

    return {
        "conversations": conversations,
        "running_ids": running_ids,
        "is_admin": user_email in ADMIN_USERS,
        "user_email": user_email,
        "pinned_conversations": pinned_conversations,
    }


@router.get("/")
def index(request: Request, user_email: str = Depends(get_current_user)):
    """Home page — dashboard with navigation, sources, starred items."""
    data = get_sidebar_data(user_email)

    # Pinned items (conversations, reports, apps)
    from .rapports import scan_interactive_apps

    pinned_raw = store.list_pinned_items()
    apps_by_slug = (
        {a["slug"]: a for a in scan_interactive_apps()} if any(p.item_type == "app" for p in pinned_raw) else {}
    )
    pinned = []
    for p in pinned_raw:
        if p.item_type == "conversation":
            conv = store.get_conversation(p.item_id, include_messages=False)
            if not conv:
                continue
            p.url = f"/explorations/{p.item_id}"
            p.pin_url = f"/api/conversations/{p.item_id}/pin"
            p.title = humanize_title(conv.title) if conv.title else p.label
            p.icon = "ri-chat-3-fill"
            p.formatted_date = format_relative_date(conv.updated_at)
            p.user_id = conv.user_id
        elif p.item_type == "report":
            report = store.get_report(int(p.item_id))
            if not report:
                continue
            p.url = f"/rapports/{p.item_id}"
            p.pin_url = f"/api/reports/{p.item_id}/pin"
            p.title = p.label or report.title
            p.icon = "ri-file-text-line"
            p.formatted_date = format_relative_date(report.updated_at)
            p.user_id = report.user_id
        elif p.item_type == "app":
            app = apps_by_slug.get(p.item_id)
            if not app:
                continue
            p.url = app["url"]
            p.pin_url = f"/api/apps/{p.item_id}/pin"
            p.title = p.label or app["title"]
            p.icon = "ri-window-fill"
            p.formatted_date = format_relative_date(app.get("updated")) if app.get("updated") else ""
            p.user_id = ", ".join(app.get("authors", [])) or None
            p.is_external = True
        pinned.append(p)

    # Knowledge sections (top-level folders only)
    knowledge_sections = list_knowledge_sections()

    return templates.TemplateResponse(
        request,
        "accueil.html",
        {
            "section": "accueil",
            "current_conv": None,
            "pinned": pinned,
            "knowledge_sections": knowledge_sections,
            **data,
        },
    )


def _group_items_by_date(items):
    """Group mixed items (conversations, reports, apps) by relative date periods."""
    now = _now_local()
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
        1: "janvier",
        2: "février",
        3: "mars",
        4: "avril",
        5: "mai",
        6: "juin",
        7: "juillet",
        8: "août",
        9: "septembre",
        10: "octobre",
        11: "novembre",
        12: "décembre",
    }

    for item in items:
        item_date = _to_local(item["sort_date"]).date()

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


@router.get("/rechercher")
def rechercher(
    request: Request,
    user_email: str = Depends(get_current_user),
    show: str = Query(default=""),
    q: str = Query(default=""),
    tag: list[str] = Query(default=[]),
):
    """Universal search page — combines conversations, reports, and apps."""
    from .rapports import scan_interactive_apps

    # Parse show param: single value, empty = all
    show_convos = show in ("", "convos", "mine")
    show_mine = show == "mine"
    show_reports = show in ("", "reports")
    show_apps = show in ("", "apps")

    tag_params = tag

    items = []

    # Conversations
    if show_convos:
        filter_user = user_email if show_mine else None
        conversations_with_tags = store.list_conversations_with_tags(
            user_id=filter_user,
            tag_names=tag_params if tag_params else None,
            limit=100,
        )
        for conv, tags in conversations_with_tags:
            if conv.title:
                conv.title = humanize_title(conv.title)
            conv.is_running = conv.needs_response
            conv.tags = tags
            conv.is_mine = conv.user_id == user_email

            # Determine icon
            conv.icon = "ri-chat-3-fill"
            for tag_obj in tags:
                if tag_obj.name == "analyse":
                    conv.icon = "ri-chat-3-fill"
                    break
                elif tag_obj.name == "meta":
                    conv.icon = "ri-settings-3-fill"
                    break
                elif tag_obj.name == "appli":
                    conv.icon = "ri-window-fill"
                    break

            items.append(
                {
                    "type": "conversation",
                    "conv": conv,
                    "tags": tags,
                    "icon": conv.icon,
                    "sort_date": conv.updated_at,
                    "formatted_date": format_relative_date(conv.updated_at),
                    "search": " ".join(
                        filter(
                            None,
                            [
                                (conv.title or "").lower(),
                                (conv.user_id or "").lower(),
                                " ".join(t.label.lower() for t in tags),
                            ],
                        )
                    ),
                }
            )

    # Reports
    if show_reports:
        reports_with_tags = store.list_reports_with_tags(
            tag_names=tag_params if tag_params else None,
            limit=100,
        )
        for report, tags in reports_with_tags:
            report.tag_objects = tags
            items.append(
                {
                    "type": "report",
                    "report": report,
                    "tags": tags,
                    "icon": "ri-file-text-line",
                    "sort_date": report.updated_at,
                    "formatted_date": format_relative_date(report.updated_at),
                    "search": " ".join(
                        filter(
                            None,
                            [
                                report.title.lower(),
                                (report.user_id or "").lower(),
                                (report.website or "").lower(),
                                (report.category or "").lower(),
                                " ".join(t.label.lower() for t in tags),
                            ],
                        )
                    ),
                }
            )

    # Apps
    if show_apps:
        for app in scan_interactive_apps():
            app_tags = set(app.get("tags", []))
            app_tags.add(app.get("website", ""))
            app_tags.add("appli")
            if tag_params and not all(t in app_tags for t in tag_params):
                continue

            sort_date = app.get("updated") or datetime.min
            items.append(
                {
                    "type": "app",
                    "app": app,
                    "tags": [],
                    "icon": "ri-window-fill",
                    "sort_date": sort_date,
                    "formatted_date": format_relative_date(sort_date) if sort_date != datetime.min else "",
                    "search": " ".join(
                        filter(
                            None,
                            [
                                app["title"].lower(),
                                (app.get("description") or "").lower(),
                                " ".join(a.lower() for a in app.get("authors", [])),
                                " ".join(t.lower() for t in app.get("tags", [])),
                            ],
                        )
                    ),
                }
            )

    # Sort by date descending
    items.sort(key=lambda x: x["sort_date"], reverse=True)

    # Group by date
    grouped_items = _group_items_by_date(items)

    # Merge tags from conversations and reports
    all_tags = {}
    if show_convos:
        filter_user = user_email if show_mine else None
        conv_tags = store.get_used_conversation_tags_by_type(
            active_tag_names=tag_params if tag_params else None,
            user_id=filter_user,
        )
        for tag_type, tag_list in conv_tags.items():
            all_tags.setdefault(tag_type, {})
            for tag_obj in tag_list:
                if tag_obj.name in all_tags[tag_type]:
                    all_tags[tag_type][tag_obj.name].count += tag_obj.count
                else:
                    all_tags[tag_type][tag_obj.name] = tag_obj

    if show_reports:
        report_tags = store.get_used_report_tags_by_type()
        for tag_type, tag_list in report_tags.items():
            all_tags.setdefault(tag_type, {})
            for tag_obj in tag_list:
                if tag_obj.name not in all_tags[tag_type]:
                    all_tags[tag_type][tag_obj.name] = tag_obj

    # Convert from {type: {name: Tag}} to {type: [Tag]}
    all_tags = {k: sorted(v.values(), key=lambda t: t.label) for k, v in all_tags.items()}

    pinned_ids = store.get_pinned_ids()

    data = get_sidebar_data(user_email)
    return templates.TemplateResponse(
        request,
        "rechercher.html",
        {
            "section": "rechercher",
            "current_conv": None,
            "grouped_items": grouped_items,
            "all_tags": all_tags,
            "active_tags": tag_params,
            "pinned_ids": pinned_ids,
            "show": show,
            "q": q,
            **data,
        },
    )


@router.get("/explorations")
def explorations(
    conv: str | None = Query(default=None),
    mine: str | None = Query(default=None),
):
    """Legacy explorations list — redirects to /rechercher."""
    if conv:
        # Validate conv is a UUID to prevent open redirect
        if _validate_conv_id(conv):
            return RedirectResponse(f"/explorations/{conv}", status_code=301)
        return RedirectResponse("/rechercher?show=convos", status_code=301)

    target = "/rechercher?show=mine" if mine == "1" else "/rechercher?show=convos"
    return RedirectResponse(target, status_code=301)


@router.get("/explorations/new")
def explorations_new(request: Request, user_email: str = Depends(get_current_user)):
    """Start a new conversation - empty chat UI."""
    data = get_sidebar_data(user_email)
    return templates.TemplateResponse(
        request,
        "explorations.html",
        {
            "section": "explorations",
            "current_conv": None,
            "is_new": True,
            "can_upload": True,
            **data,
        },
    )


@router.get("/explorations/{conv_id}")
def explorations_conversation(conv_id: str, request: Request, user_email: str = Depends(get_current_user)):
    """View a specific conversation.

    Allows viewing conversations owned by other users (shared via UUID link).
    The owner's email is shown in the header for shared conversations.
    """
    # Try to get conversation without user filter (allow shared access)
    current_conv = store.get_conversation(conv_id, include_messages=False)

    if not current_conv:
        return RedirectResponse("/rechercher?show=convos", status_code=302)

    # Check if this is a shared conversation (owned by someone else)
    is_shared = current_conv.user_id and current_conv.user_id != user_email
    owner_email = current_conv.user_id if is_shared else None

    if current_conv.title:
        current_conv.title = humanize_title(current_conv.title)

    # Determine if file uploads are allowed for this conversation
    can_upload = not is_shared and current_conv.conv_type in ("exploration", None)

    # Admin can relaunch shared conversations stuck on a user message
    can_relaunch = (
        is_shared
        and user_email in ADMIN_USERS
        and not current_conv.needs_response
        and store.get_last_message_role(conv_id) == "user"
    )

    data = get_sidebar_data(user_email)
    return templates.TemplateResponse(
        request,
        "explorations.html",
        {
            "section": "explorations",
            "current_conv": current_conv,
            "is_shared": is_shared,
            "owner_email": owner_email,
            "can_upload": can_upload,
            "can_relaunch": can_relaunch,
            **data,
        },
    )


@router.get("/connaissances")
def connaissances(
    request: Request,
    user_email: str = Depends(get_current_user),
    file: str | None = Query(default=None),
    section_filter: str | None = Query(default=None, alias="section"),
):
    """Connaissances section - knowledge file browser (index)."""
    # Redirect old ?file= pattern to RESTful URL
    if file:
        # Validate file path contains only safe characters to prevent open redirect
        if re.match(r"^[a-zA-Z0-9_\-./]+$", file) and ".." not in file:
            return RedirectResponse(f"/connaissances/{file}", status_code=301)
        return RedirectResponse("/connaissances", status_code=301)

    data = get_sidebar_data(user_email)
    categories = list_knowledge_files()
    if section_filter:
        categories = {k: v for k, v in categories.items() if k == section_filter or k.startswith(section_filter + "/")}
    active_conversations = store.list_active_knowledge_conversations()
    active_files = {c.file_path: c for c in active_conversations if c.file_path}

    return templates.TemplateResponse(
        request,
        "connaissances.html",
        {
            "section": "connaissances",
            "categories": categories,
            "current_file": None,
            "file_content": None,
            "current_conv": None,
            "staged_files": [],
            "active_files": active_files,
            "active_conversations": active_conversations,
            "feature_knowledge_chat": FEATURE_KNOWLEDGE_CHAT,
            **data,
        },
    )


@router.get("/connaissances/{file_path:path}")
def connaissances_file(
    file_path: str,
    request: Request,
    user_email: str = Depends(get_current_user),
    conv: str | None = Query(default=None),
):
    """Connaissances section - view a specific knowledge file."""
    data = get_sidebar_data(user_email)

    validated_path = validate_knowledge_path(file_path)
    if not validated_path:
        return templates.TemplateResponse(
            request,
            "connaissances.html",
            {
                "section": "connaissances",
                "error": "Fichier non trouvé",
                "categories": list_knowledge_files(),
                "active_conversations": store.list_active_knowledge_conversations(),
                "feature_knowledge_chat": FEATURE_KNOWLEDGE_CHAT,
                **data,
            },
        )

    file_content = validated_path.read_text()
    current_conv = None
    staged_files = []

    if conv:
        current_conv = store.get_conversation(conv, include_messages=False)
    else:
        current_conv = store.get_active_knowledge_conversation(file_path)

    if current_conv:
        staged_files = list_staged_files(current_conv.id)

    categories = list_knowledge_files()
    active_conversations = store.list_active_knowledge_conversations()
    active_files = {c.file_path: c for c in active_conversations if c.file_path}

    return templates.TemplateResponse(
        request,
        "connaissances.html",
        {
            "section": "connaissances",
            "categories": categories,
            "current_file": file_path,
            "file_content": file_content,
            "current_conv": current_conv,
            "staged_files": staged_files,
            "active_files": active_files,
            "active_conversations": active_conversations,
            "feature_knowledge_chat": FEATURE_KNOWLEDGE_CHAT,
            **data,
        },
    )


@router.get("/recherche")
@router.get("/recherche/{page_id}")
def recherche_redirect(request: Request, page_id: str = ""):
    """Legacy redirect: /recherche → /terrain."""
    target = "/terrain"
    if page_id:
        target += f"/{page_id}"
    if request.url.query:
        target += f"?{request.url.query}"
    return RedirectResponse(target, status_code=301)


@router.get("/terrain")
def terrain(
    request: Request,
    user_email: str = Depends(get_current_user),
    q: str = Query(default=""),
    similar: int | None = Query(default=None),
    db: list[str] = Query(default=[]),
    type: list[str] = Query(default=[]),
):
    """Terrain - semantic search across the Notion research corpus."""
    data = get_sidebar_data(user_email)
    corpus_stats = get_corpus_stats()

    q = q.strip()
    db_filter = set(db) or {"entretiens"}
    type_filter = set(type)

    results = None
    similar_source = None
    elapsed = None
    error = None

    if q:
        try:
            t0 = time.monotonic()
            results, _ = search_corpus(q, limit=25, db_filter=db_filter, type_filter=type_filter)
            elapsed = round(time.monotonic() - t0, 1)
        except Exception:
            logger.exception("Research search failed")
            error = "La recherche a échoué"
    elif similar:
        try:
            t0 = time.monotonic()
            results, similar_source = find_similar_pages(similar, limit=20)
            elapsed = round(time.monotonic() - t0, 1)
        except Exception:
            logger.exception("Research similar failed")
            error = "La recherche de pages similaires a échoué"

    return templates.TemplateResponse(
        request,
        "terrain.html",
        {
            "section": "terrain",
            "current_conv": None,
            "current_page": None,
            "corpus_stats": corpus_stats,
            "query": q,
            "results": results,
            "similar_id": similar,
            "similar_source": similar_source,
            "elapsed": elapsed,
            "error": error,
            "active_dbs": db_filter,
            "active_types": type_filter,
            **data,
        },
    )


@router.get("/terrain/{page_id}")
def terrain_page(page_id: str, request: Request, user_email: str = Depends(get_current_user)):
    """Terrain - page detail view."""
    data = get_sidebar_data(user_email)
    page = get_page(page_id)
    if not page:
        return RedirectResponse("/terrain", status_code=302)

    # Filter properties for display (skip internal ones)
    skip_props = {"Type", "Date", "Date calculee", "Nom", "Name", "title"}
    visible_props = {}
    for k, v in (page.get("properties") or {}).items():
        if k in skip_props or v is None or v == "":
            continue
        if isinstance(v, list):
            if not v:
                continue
            # Skip UUID lists (relation IDs)
            if all(isinstance(x, str) and len(x) == 36 and "-" in x for x in v):
                continue
        if isinstance(v, str) and len(v) == 36 and "-" in v:
            continue
        visible_props[k] = v

    return templates.TemplateResponse(
        request,
        "terrain.html",
        {
            "section": "terrain",
            "current_conv": None,
            "current_page": page,
            "visible_props": visible_props,
            "corpus_stats": None,
            **data,
        },
    )


def is_admin(user_email: str | None) -> bool:
    """Check if a user is an admin."""
    return user_email in ADMIN_USERS
