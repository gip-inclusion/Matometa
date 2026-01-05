"""Configuration for the Matometa web application."""

import os
from pathlib import Path

# Base directory (Matometa project root)
BASE_DIR = Path(__file__).parent.parent.resolve()

# Agent backend: "cli" or "sdk"
AGENT_BACKEND = os.getenv("AGENT_BACKEND", "cli")

# Claude CLI path (uses system default if not set)
CLAUDE_CLI = os.getenv("CLAUDE_CLI", "claude")

# Allowed tools for the agent (safe subset)
# Bash patterns: sqlite3, curl, python/python3, rg, grep, cat, ls, head, tail, jq, source
ALLOWED_TOOLS = os.getenv("ALLOWED_TOOLS",
    "Read,Write,Edit,Glob,Grep,"
    "Bash(sqlite3:*),Bash(curl:*),Bash(python:*),Bash(python3:*),"
    "Bash(rg:*),Bash(grep:*),Bash(cat:*),Bash(ls:*),Bash(head:*),Bash(tail:*),Bash(wc:*),"
    "Bash(jq:*),Bash(source:*)"
)

# Web server settings
HOST = os.getenv("WEB_HOST", "127.0.0.1")
PORT = int(os.getenv("WEB_PORT", "5000"))
DEBUG = os.getenv("WEB_DEBUG", "true").lower() == "true"
