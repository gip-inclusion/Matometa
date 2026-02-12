"""Flask blueprints for API routes."""

from .conversations import bp as conversations_bp
from .reports import bp as reports_bp
from .knowledge import bp as knowledge_bp
from .logs import bp as logs_bp
from .html import bp as html_bp
from .rapports import bp as rapports_bp
from .query import bp as query_bp
from .auth import bp as auth_bp
from .cron import bp as cron_bp

__all__ = [
    "conversations_bp",
    "reports_bp",
    "knowledge_bp",
    "logs_bp",
    "html_bp",
    "rapports_bp",
    "query_bp",
    "auth_bp",
    "cron_bp",
]
