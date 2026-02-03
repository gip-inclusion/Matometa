"""Configuration for the Matometa web application."""

import os
from pathlib import Path

# Base directory (Matometa project root)
BASE_DIR = Path(__file__).parent.parent.resolve()

# Data directory - can be overridden for local development with remote data
# Default: ./data (relative to BASE_DIR)
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).resolve()

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

# Public URL for generating links (used by agent for shareable URLs)
# Defaults to local dev URL if not set
PUBLIC_URL = os.getenv("PUBLIC_URL", f"http://{HOST}:{PORT}").rstrip("/")

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

# Database: uses PostgreSQL if DATABASE_URL is set, otherwise SQLite
DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = DATA_DIR / "matometa.db"

# Agent-produced scripts directory
SCRIPTS_DIR = DATA_DIR / "scripts"

# Interactive files directory (agent-generated exports, dashboards)
# Used for local storage fallback when S3 is not configured
INTERACTIVE_DIR = DATA_DIR / "interactive"

# Common shared assets (CSS/JS frameworks used by interactive apps)
# Always relative to BASE_DIR (framework code, not per-environment data)
COMMON_DIR = BASE_DIR / "data" / "common"

# Uploads directory for user-uploaded files in chat
UPLOADS_DIR = DATA_DIR / "uploads"

# Modified files directory (writable copies of uploaded files for agent modifications)
MODIFIED_DIR = DATA_DIR / "modified"

# File upload limits
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 200 * 1024 * 1024))  # 200 MB default
# Text file size threshold for including content directly in conversation
TEXT_FILE_INLINE_LIMIT = int(os.getenv("TEXT_FILE_INLINE_LIMIT", 50 * 1024))  # 50 KB default

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
