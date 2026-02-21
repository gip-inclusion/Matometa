"""Shared FastAPI dependencies and template helpers."""

import os
import re

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import config


# --- Auth dependencies ---

def get_current_user(request: Request) -> str:
    """Extract authenticated user email from oauth2-proxy headers."""
    return request.headers.get("X-Forwarded-Email") or config.DEFAULT_USER


def get_current_user_name(request: Request) -> str | None:
    """Extract authenticated user name from oauth2-proxy headers."""
    return request.headers.get("X-Forwarded-User")


# --- Jinja2 templates ---

templates = Jinja2Templates(directory="web/templates")


# Custom filters

TYPE_ICONS = {
    "❝ Verbatim": "ri-chat-quote-line",
    "👀 Observation": "ri-eye-line",
    "🗣 Entretien": "ri-mic-line",
    "📂 Terrain": "ri-folder-open-line",
    "🤼 Open Lab": "ri-group-line",
    "🧮 Questionnaire / quanti": "ri-bar-chart-box-line",
    "📂 Événement": "ri-calendar-event-line",
    "🗒️ Note": "ri-sticky-note-line",
    "🎤  Retex": "ri-presentation-line",
    "📖 Lecture": "ri-book-read-line",
}
DB_ICONS = {
    "entretiens": "ri-mic-line",
    "thematiques": "ri-bookmark-line",
    "segments": "ri-user-settings-line",
    "profils": "ri-user-line",
    "hypotheses": "ri-question-line",
    "conclusions": "ri-check-double-line",
}


def _regex_replace_filter(value, pattern, replacement=""):
    return re.sub(pattern, replacement, str(value))


def _result_icon_filter(result):
    """Get the icon class for a search result dict."""
    pt = result.get("page_type")
    if pt and pt in TYPE_ICONS:
        return TYPE_ICONS[pt]
    return DB_ICONS.get(result.get("database_key"), "ri-file-text-line")


templates.env.filters["regex_replace"] = _regex_replace_filter
templates.env.filters["result_icon"] = _result_icon_filter


def _static_url(path: str) -> str:
    """Return /static/path?v=mtime for cache busting."""
    try:
        mtime = int(os.path.getmtime(f"web/static/{path}"))
    except OSError:
        mtime = 0
    return f"/static/{path}?v={mtime}"


templates.env.globals["static_url"] = _static_url
