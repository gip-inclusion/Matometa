"""LLM client for the watchdog agent — Ollama cloud API (/api/chat)."""

import json
import logging
import urllib.request
from watchdog import config

logger = logging.getLogger(__name__)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "docker",
            "description": "Run a docker CLI command. Example: 'ps -a --format table', 'logs --tail 20 container_name', 'restart container_name', 'system df'",
            "parameters": {
                "type": "object",
                "properties": {"args": {"type": "string", "description": "Arguments to pass to `docker` CLI"}},
                "required": ["args"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run a shell command for system diagnostics. Example: 'df -h /', 'free -h', 'uptime'",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Shell command to execute"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sql",
            "description": "Execute a SQL query on the matometa database. Use for reading conversation states, clearing stuck flags, checking project status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL query to execute"},
                    "write": {"type": "boolean", "description": "Set true for UPDATE/INSERT/DELETE (default false)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_smoke",
            "description": "Run a headless browser smoke test on a URL. Returns pass/fail with errors and screenshot path.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL to test"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report",
            "description": "Log a finding or action to the watchdog report. Use after each significant observation or action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "What happened (natural language)"},
                    "severity": {"type": "string", "enum": ["info", "warn", "critical"], "description": "Severity level"},
                },
                "required": ["message", "severity"],
            },
        },
    },
]


def chat(messages: list[dict], use_tools: bool = True) -> dict:
    """Call Ollama cloud API (/api/chat).

    Returns the message dict with 'content' and/or 'tool_calls'.
    Ollama native format: tool_calls[].function.arguments is a dict (not JSON string).
    """
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.3},
    }
    if use_tools:
        payload["tools"] = TOOLS_SCHEMA

    data = json.dumps(payload).encode()
    # Note: Ollama cloud rejects Content-Type: application/json on /api/chat
    headers = {
        "Authorization": f"Bearer {config.OLLAMA_API_KEY}",
    }

    req = urllib.request.Request(
        f"{config.OLLAMA_API_URL}/api/chat",
        data=data,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result.get("message", {})
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return {"role": "assistant", "content": f"[LLM ERROR] {e}"}
