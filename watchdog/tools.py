"""Tool execution for the watchdog agent.

Each tool function takes the LLM's arguments and returns a string result.
"""

import json
import logging
import os
import sqlite3
import subprocess
from datetime import datetime, timezone

from watchdog import config
from watchdog.memory import append_report
from watchdog.reporting import log_event, send_webhook

logger = logging.getLogger(__name__)

# Safety: commands the agent is NOT allowed to run
DOCKER_BLOCKED = {"rm -f", "rmi -f", "volume rm", "network rm", "system prune -a"}
SHELL_BLOCKED = {"rm -rf", "mkfs", "dd if=", "shutdown", "reboot", "kill -9"}


def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool call and return the result string."""
    try:
        if name == "docker":
            return _tool_docker(arguments)
        elif name == "shell":
            return _tool_shell(arguments)
        elif name == "sql":
            return _tool_sql(arguments)
        elif name == "browser_smoke":
            return _tool_browser_smoke(arguments)
        elif name == "report":
            return _tool_report(arguments)
        else:
            return f"Unknown tool: {name}"
    except Exception as e:
        logger.error("Tool %s failed: %s", name, e)
        return f"Tool error: {e}"


def _tool_docker(args: dict) -> str:
    """Run a docker CLI command with safety checks."""
    cmd_args = args.get("args", "")

    # Safety check
    for blocked in DOCKER_BLOCKED:
        if blocked in cmd_args:
            return f"BLOCKED: '{blocked}' is not allowed. Use safer alternatives."

    cmd = f"docker {cmd_args}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        output = (result.stdout + result.stderr).strip()
        # Truncate long output
        if len(output) > 3000:
            output = output[:3000] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30s"


def _tool_shell(args: dict) -> str:
    """Run a shell command for system diagnostics."""
    command = args.get("command", "")

    # Safety check
    for blocked in SHELL_BLOCKED:
        if blocked in command:
            return f"BLOCKED: '{blocked}' is not allowed."

    # Only allow read-only diagnostic commands
    allowed_prefixes = ("df", "free", "uptime", "cat /proc", "ls", "du", "top -bn1", "ps aux", "wc", "docker")
    if not any(command.strip().startswith(p) for p in allowed_prefixes):
        return f"BLOCKED: Only diagnostic commands are allowed. Use the 'docker' tool for Docker commands, 'shell' for: {', '.join(p for p in allowed_prefixes if p != 'docker')}"

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=15
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 2000:
            output = output[:2000] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 15s"


def _tool_sql(args: dict) -> str:
    """Execute SQL on the matometa database."""
    query = args.get("query", "")
    is_write = args.get("write", False)

    # Safety: block destructive operations
    upper = query.upper().strip()
    if any(kw in upper for kw in ("DROP ", "TRUNCATE ", "ALTER ", "CREATE ", "DELETE FROM conversations", "DELETE FROM messages")):
        return "BLOCKED: Destructive DDL/DML not allowed."

    # Only allow UPDATE on specific safe columns
    if is_write and upper.startswith("UPDATE"):
        safe_updates = ("needs_response",)
        if not any(col in query.lower() for col in safe_updates):
            return f"BLOCKED: Only updates to {safe_updates} are allowed."

    try:
        db_path = config.SQLITE_PATH
        if not os.path.exists(db_path):
            return f"Database not found at {db_path}"

        conn = sqlite3.connect(db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(query)

        if is_write:
            conn.commit()
            return f"OK: {cursor.rowcount} row(s) affected"

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "No results"

        # Format as readable table
        headers = rows[0].keys()
        lines = ["\t".join(headers)]
        for row in rows[:50]:  # limit output
            lines.append("\t".join(str(row[h]) for h in headers))

        return "\n".join(lines)

    except Exception as e:
        return f"SQL error: {e}"


def _tool_browser_smoke(args: dict) -> str:
    """Run browser smoke test via the existing lib."""
    url = args.get("url", "")
    try:
        # Import from the existing matometa lib
        import sys
        sys.path.insert(0, "/app")
        from lib.browser_smoke import smoke_test, browser_available

        if not browser_available():
            return "Browser not available (sidecar container not running)"

        result = smoke_test(url, project_id="watchdog", timeout=30)
        return json.dumps(result, indent=2)
    except ImportError:
        # Fallback: try direct agent-browser call
        try:
            r = subprocess.run(
                ["docker", "exec", "matometa-browser", "npx", "agent-browser", "open", url],
                capture_output=True, text=True, timeout=30,
            )
            return r.stdout + r.stderr if r.returncode == 0 else f"Browser test failed: {r.stderr}"
        except Exception as e:
            return f"Browser smoke unavailable: {e}"


def _tool_report(args: dict) -> str:
    """Log a report finding."""
    message = args.get("message", "")
    severity = args.get("severity", "info")

    report = {
        "message": message,
        "severity": severity,
    }

    # Log to JSONL file
    log_event(report)

    # Save to agent memory
    append_report({"summary": message, "severity": severity})

    # Send webhook for warn/critical
    if severity in ("warn", "critical") and config.WEBHOOK_URL:
        send_webhook(report)

    return f"Reported [{severity}]: {message}"
