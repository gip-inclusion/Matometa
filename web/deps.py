"""Shared FastAPI dependencies and template helpers."""

import os
import re

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import config


def get_current_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-Email") or config.DEFAULT_USER


def get_current_user_name(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-User")


templates = Jinja2Templates(directory="web/templates")

# Custom filters


def _regex_replace_filter(value, pattern, replacement=""):
    return re.sub(pattern, replacement, str(value))


templates.env.filters["regex_replace"] = _regex_replace_filter


def _static_url(path: str) -> str:
    try:
        mtime = int(os.path.getmtime(f"web/static/{path}"))
    except OSError:
        mtime = 0
    return f"/static/{path}?v={mtime}"


templates.env.globals["static_url"] = _static_url


def _format_relative_date_global(dt):
    """Lazy import to avoid circular dependency with routes.html."""
    from .routes.html import format_relative_date

    return format_relative_date(dt)


templates.env.globals["format_relative_date"] = _format_relative_date_global
