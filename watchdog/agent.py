"""Watchdog AI Agent — ReAct loop with tools.

Observes the system, reasons about problems, takes corrective actions, reports.
Uses Ollama cloud API as the LLM brain with a rolling memory of past reports.
"""

import json
import logging
import time
from datetime import datetime, timezone

from watchdog import config
from watchdog.llm import chat
from watchdog.memory import format_memory_for_prompt, append_report
from watchdog.tools import execute_tool
from watchdog.reporting import log_event

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a watchdog agent for the Matometa platform running on a Scaleway VPS.

## Your role
You monitor the health of Docker containers, the database, deployed web apps, and system resources.
You fix what you can and report what you can't. You are conservative — don't restart things unnecessarily.

## Server topology
- Host: Scaleway DEV1-L (12GB RAM, ~4 vCPU, 27G disk)
- Main app: matometa-matometa-1 (Flask, port 5002→5000)
- Git server: matometa-gitea (port 3300→3000, SSH 2222→22)
- Browser sidecar: matometa-browser (headless Chromium for smoke tests)
- Project containers: named like <slug>-<env>-<service>-1 (e.g. sure-maple-staging-app-1)
  - Each project has: app, and optionally db (PostgreSQL), redis, worker
  - If the app is crash-looping, check if its db/redis dependencies are running first

## Known failure patterns
1. **Container dependencies not starting after reboot**: db/redis containers exit cleanly but don't restart, causing app containers to crash-loop on DNS resolution failures. Fix: start the dependencies, then restart the app.
2. **needs_response stuck at 1**: In the conversations table, needs_response=1 means the AI is processing. If it stays stuck for >5 minutes with no PM activity, the flag is zombie. Fix: UPDATE conversations SET needs_response=0 WHERE id=<conv_id>
3. **Disk fills up**: Docker images and volumes accumulate. Safe to prune dangling images and unused volumes.
4. **RAM pressure**: If available RAM drops below 10%, identify the heaviest container but do NOT kill it. Report for human attention.

## Your tools
- `docker`: Run any docker CLI command (read-only + restart/start)
- `shell`: System diagnostics (df, free, uptime, etc.)
- `sql`: Query/update the matometa SQLite database
- `browser_smoke`: Run headless browser test on a URL
- `report`: Log a finding with severity (info/warn/critical)

## Instructions
1. Start by observing: run `docker ps -a` (via docker tool), `df -h /` and `free -h` (via shell tool), then check stuck flags (via sql tool)
2. If you find issues, investigate (read logs, check dependencies)
3. Fix what you can (restart containers, clear stuck flags, prune disk if >80%)
4. Report everything you did and everything that needs human attention
5. Be concise. Don't over-explain. Act like an experienced sysadmin.
6. **IMPORTANT**: You MUST end with a `report` tool call summarizing what you found and did. This is mandatory.
7. If a tool returns an error, do NOT retry the same command. Adapt or move on.
8. Use the `docker` tool for all Docker commands, NOT the `shell` tool.
9. Aim to complete in under 10 tool calls. Don't over-investigate if everything looks fine.

## Memory
Your recent reports are included below. Use them to avoid repeating actions or to detect recurring patterns.

{memory}
"""

MAX_TOOL_ROUNDS = 15


def build_system_prompt() -> str:
    """Build the system prompt with current memory."""
    memory = format_memory_for_prompt()
    return SYSTEM_PROMPT.format(memory=memory)


def run_cycle() -> dict:
    """Run one observe-think-act-report cycle.

    Returns a summary dict of the cycle.
    """
    started = datetime.now(timezone.utc)
    logger.info("=== Watchdog cycle started at %s ===", started.isoformat())

    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": (
            f"Run your periodic health check. Current time: {started.isoformat()}. "
            "Check containers, stuck flags, disk/RAM. Run smoke tests on deployed apps if browser is available. "
            "Fix issues and report findings."
        )},
    ]

    actions_taken = []
    tool_calls_count = 0

    for round_num in range(MAX_TOOL_ROUNDS):
        response = chat(messages, use_tools=True)

        # Check for LLM error
        content = response.get("content", "")
        if content and content.startswith("[LLM ERROR]"):
            logger.error("LLM failed: %s", content)
            log_event({"severity": "critical", "message": f"LLM error during cycle: {content}"})
            break

        # If the LLM returns text without tool calls, the cycle is done
        tool_calls = response.get("tool_calls", [])

        if not tool_calls:
            if content:
                logger.info("Agent final message: %s", content[:500])
            break

        # Execute tool calls
        messages.append(response)

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            # Ollama returns arguments as dict; OpenAI-compat as JSON string
            if isinstance(raw_args, str):
                try:
                    tool_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    tool_args = {}
            else:
                tool_args = raw_args

            logger.info("Tool call [%d/%d]: %s(%s)",
                        round_num + 1, MAX_TOOL_ROUNDS, tool_name,
                        json.dumps(tool_args)[:200])

            result = execute_tool(tool_name, tool_args)
            tool_calls_count += 1

            actions_taken.append(f"{tool_name}({json.dumps(tool_args)[:100]})")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{round_num}_{tool_name}"),
                "content": result,
            })

    duration_s = (datetime.now(timezone.utc) - started).total_seconds()

    summary = {
        "started": started.isoformat(),
        "duration_s": round(duration_s, 1),
        "tool_calls": tool_calls_count,
        "actions": actions_taken,
        "final_message": content[:500] if content else "",
    }

    logger.info("=== Cycle done: %d tool calls in %.1fs ===", tool_calls_count, duration_s)

    return summary
