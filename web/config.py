"""Configuration for the Matometa web application."""

import os
from pathlib import Path

# Base directory (Matometa project root)
BASE_DIR = Path(__file__).parent.parent.resolve()

# Agent backend: "cli" or "sdk"
AGENT_BACKEND = os.getenv("AGENT_BACKEND", "cli")

# Claude CLI path (uses system default if not set)
CLAUDE_CLI = os.getenv("CLAUDE_CLI", "claude")

# Allowed tools for the agent (CLI backend only - SDK ignores this)
# Bash patterns use glob wildcards (* matches anything)
# NOTE: Real security boundary is the container, not LLM tool restrictions
ALLOWED_TOOLS = os.getenv("ALLOWED_TOOLS",
    "Read,Write,Edit,Glob,Grep,"
    "Bash(curl:*inclusion.gouv.fr*),Bash(curl:*inclusion.beta.gouv.fr*),"
    "Bash(curl:*github.com/gip-inclusion*),Bash(curl:*github.com/betagouv*),"
    "Bash(curl:*raw.githubusercontent.com/gip-inclusion*),Bash(curl:*raw.githubusercontent.com/betagouv*),"
    "Bash(curl:*api.github.com*),"
    "Bash(jq:*),Bash(sqlite3:*),"
    "Bash(python:*),Bash(python3:*),"
    "Bash(.venv/bin/python:*)"
)

# Web server settings
HOST = os.getenv("WEB_HOST", "127.0.0.1")
PORT = int(os.getenv("WEB_PORT", "5000"))
DEBUG = os.getenv("WEB_DEBUG", "true").lower() == "true"

# Default user for local development (when oauth-proxy not present)
DEFAULT_USER = os.getenv("DEFAULT_USER", "admin@localhost")

# Admin users who can see all conversations (comma-separated emails)
ADMIN_USERS = [
    email.strip()
    for email in os.getenv(
        "ADMIN_USERS", "louisjean.teitelbaum@inclusion.gouv.fr,admin@localhost"
    ).split(",")
    if email.strip()
]

# Database
# If DATABASE_URL is set (Scalingo provides this), use PostgreSQL
# Otherwise, fall back to SQLite for local development
DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = BASE_DIR / "data" / "matometa.db"

# Logging
LOG_FILE = BASE_DIR / "data" / "agent.log"
# Don't create log directory here - let app.py handle it based on environment

# Interactive files directory (agent-generated exports, dashboards)
# Note: On Scalingo, this is ephemeral storage - files are lost on deploy/restart
INTERACTIVE_DIR = BASE_DIR / "data" / "interactive"

# Additional directories the agent can access (beyond working directory)
ADDITIONAL_DIRS = ["/tmp"]

# Feature flags
FEATURE_KNOWLEDGE_CHAT = False  # Chat from Connaissance tab disabled (requires GitHub PAT)
