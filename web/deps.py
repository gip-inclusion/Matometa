"""Shared FastAPI dependencies and template helpers."""

import os
import re

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import config
from .helpers import format_relative_date


def get_current_user(request: Request) -> str:
    return request.headers.get("X-Forwarded-Email") or config.DEFAULT_USER


def get_current_user_name(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-User")


templates = Jinja2Templates(directory="web/templates")

# Custom filters


def regex_replace_filter(value, pattern, replacement=""):
    return re.sub(pattern, replacement, str(value))


templates.env.filters["regex_replace"] = regex_replace_filter


def static_url(path: str) -> str:
    try:
        mtime = int(os.path.getmtime(f"web/static/{path}"))
    except OSError:
        mtime = 0
    return f"/static/{path}?v={mtime}"


templates.env.globals["static_url"] = static_url

templates.env.globals["format_relative_date"] = format_relative_date
