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

# Database backend: "sqlite" (default) or "postgres"
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite")
DATABASE_URL = os.getenv("DATABASE_URL")  # Required when DB_BACKEND=postgres
SQLITE_PATH = BASE_DIR / "data" / "matometa.db"

# Interactive files directory (agent-generated exports, dashboards)
# Used for local storage fallback when S3 is not configured
INTERACTIVE_DIR = BASE_DIR / "data" / "interactive"

# S3-compatible object storage for interactive files
# If configured, files are stored in S3 instead of local filesystem
# Works with AWS S3, Scaleway Object Storage, MinIO, etc.
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ENDPOINT = os.getenv("S3_ENDPOINT")  # e.g., https://s3.fr-par.scw.cloud
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_REGION = os.getenv("S3_REGION", "fr-par")
S3_PREFIX = os.getenv("S3_PREFIX", "interactive/")  # Key prefix for all files

# S3 is enabled if bucket and credentials are configured
USE_S3 = bool(S3_BUCKET and S3_ACCESS_KEY and S3_SECRET_KEY)

# Additional directories the agent can access (beyond working directory)
ADDITIONAL_DIRS = ["/tmp"]

# Feature flags
FEATURE_KNOWLEDGE_CHAT = False  # Chat from Connaissance tab disabled (requires GitHub PAT)
