"""Configuration for the Matometa web application."""

import os
from pathlib import Path

# Base directory (Matometa project root)
BASE_DIR = Path(__file__).parent.parent.resolve()

# Data directory - can be overridden for local development with remote data
# Default: ./data (relative to BASE_DIR)
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).resolve()

# Agent backend: "ollama", "cli" or "sdk"
AGENT_BACKEND = os.getenv("AGENT_BACKEND", "ollama").lower()

# LLM backend for short prompts (titles, tags). Defaults to AGENT_BACKEND.
LLM_BACKEND = os.getenv("LLM_BACKEND", "").strip().lower() or AGENT_BACKEND

# Claude CLI path (uses system default if not set)
CLAUDE_CLI = os.getenv("CLAUDE_CLI", "claude")

# Claude model (used by SDK and CLI helper)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

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

# Ollama settings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-coder-next")
OLLAMA_TITLE_MODEL = os.getenv("OLLAMA_TITLE_MODEL", OLLAMA_MODEL)
OLLAMA_TAG_MODEL = os.getenv("OLLAMA_TAG_MODEL", OLLAMA_MODEL)
OLLAMA_REQUEST_TIMEOUT = float(os.getenv("OLLAMA_REQUEST_TIMEOUT", "120"))
OLLAMA_STREAM = os.getenv("OLLAMA_STREAM", "true").lower() == "true"
OLLAMA_STREAM_CHUNK_SIZE = int(os.getenv("OLLAMA_STREAM_CHUNK_SIZE", "200"))
OLLAMA_MAX_HISTORY_CHARS = int(os.getenv("OLLAMA_MAX_HISTORY_CHARS", "50000"))
OLLAMA_TOOL_MAX_STEPS = min(int(os.getenv("OLLAMA_TOOL_MAX_STEPS", "6")), 20)
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "0"))
OLLAMA_MAX_OUTPUT_CHARS = int(os.getenv("OLLAMA_MAX_OUTPUT_CHARS", "30000"))
OLLAMA_BASH_TIMEOUT = int(os.getenv("OLLAMA_BASH_TIMEOUT", "300"))

# Backend capability helpers
USES_CLAUDE_CLI = AGENT_BACKEND == "cli" or LLM_BACKEND == "cli"

# Web server settings
HOST = os.getenv("WEB_HOST", "127.0.0.1")
PORT = int(os.getenv("WEB_PORT", "5000"))
DEBUG = os.getenv("WEB_DEBUG", "true").lower() == "true"

# Base URL for generating absolute links (e.g. BASE_URL=https://matometa.ljt.cc/)
# Only needed when sharing links outside the app; prefer relative URLs otherwise.
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

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

# Research corpus (Notion "Connaissance du terrain")
NOTION_RESEARCH_DB = DATA_DIR / "notion_research.db"
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY")

# Feature flags
FEATURE_KNOWLEDGE_CHAT = False  # Chat from Connaissance tab disabled (requires GitHub PAT)
