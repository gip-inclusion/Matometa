"""CLI backend - spawns claude CLI process."""

import asyncio
import json
import logging
import os
import signal
from typing import AsyncIterator, Optional

from .. import config
from .base import AgentBackend, AgentMessage, build_system_prompt

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class CLIBackend(AgentBackend):
    """Agent backend that spawns the claude CLI."""

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def _build_env(self, conversation_id: str) -> dict:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        return env

    def _extra_cmd_args(self) -> list[str]:
        """Extra CLI arguments appended before -p. Override in subclasses."""
        return []

    def _build_prompt(self, message: str, history: list[dict]) -> str:
        if not history:
            return message

        parts = []
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"User: {content}")
            else:
                parts.append(f"Assistant: {content}")

        parts.append(f"User: {message}")
        return "\n\n".join(parts)

    async def send_message(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentMessage]:
        """Spawn claude CLI and stream responses.

        If session resume fails (corruption, crash with no output, etc.),
        automatically retries without session (using history instead).
        """
        if not session_id:
            async for msg in self._run_cli(conversation_id, message, history, None):
                yield msg
            return

        # Try with session first, retry without on failure
        retry_without_session = False
        had_useful_output = False

        async for msg in self._run_cli(conversation_id, message, history, session_id):
            if msg.type == "error":
                error_str = str(msg.content)
                if "tool_use ids must be unique" in error_str:
                    logger.warning(f"Session {session_id} corrupted (duplicate IDs), retrying without resume")
                    retry_without_session = True
                    break
                # CLI crashed with no useful output — likely session corruption
                if not had_useful_output:
                    logger.warning(f"Session {session_id} failed (exit with no output), retrying without resume")
                    retry_without_session = True
                    break
            if msg.type in ("assistant", "tool_use"):
                had_useful_output = True
            yield msg

        if retry_without_session:
            yield AgentMessage(
                type="system",
                content="Session corrompue, redémarrage...",
                raw={"retry": True},
            )
            async for msg in self._run_cli(conversation_id, message, history, None):
                yield msg

    async def _run_cli(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str],
    ) -> AsyncIterator[AgentMessage]:
        """Internal: run the CLI process."""
        # When resuming a session, don't include history in prompt (session already has it)
        # This prevents duplicate tool_use IDs which cause API errors
        if session_id:
            prompt = message
        else:
            prompt = self._build_prompt(message, history)

        cmd = [
            config.CLAUDE_CLI,
            "--output-format",
            "stream-json",
            "--verbose",
        ]

        # Add additional directories the agent can access
        for d in config.ADDITIONAL_DIRS:
            cmd.extend(["--add-dir", d])

        # Add CLAUDE.md as system prompt
        system_prompt = build_system_prompt()
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        # In a container, skip permission checks (container is the security boundary).
        # Outside containers, restrict tools to a whitelist.
        if os.getenv("CONTAINER_ENV"):
            cmd.append("--dangerously-skip-permissions")
        elif config.ALLOWED_TOOLS:
            cmd.extend(["--allowedTools", config.ALLOWED_TOOLS])

        cmd.extend(["-p", prompt])

        # Add resume flag if we have a session
        if session_id:
            cmd.extend(["--resume", session_id])

        cmd.extend(self._extra_cmd_args())

        logger.info(
            f"Starting claude CLI: {' '.join(cmd[:4])}... (prompt length: {len(prompt)}, session: {session_id or 'none'})"
        )

        env = self._build_env(conversation_id)

        # Spawn process (10 MB buffer to handle large tool results)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.BASE_DIR),
            env=env,
            limit=10 * 1024 * 1024,
        )

        logger.info(f"Process started with PID: {process.pid}")

        self._processes[conversation_id] = process

        try:
            # Read stdout line by line
            line_count = 0
            while True:
                line = await process.stdout.readline()
                if not line:
                    logger.debug(f"EOF reached after {line_count} lines")
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                line_count += 1
                logger.debug("Line %d: %s", line_count, line_str)

                # Parse JSON event
                try:
                    event = json.loads(line_str)
                    agent_msg = self._parse_event(event)
                    if agent_msg:
                        logger.debug(f"Parsed event: {agent_msg.type}")
                        yield agent_msg
                except json.JSONDecodeError:
                    # Non-JSON output, emit as system message
                    logger.warning("Non-JSON line: %s", line_str)
                    yield AgentMessage(
                        type="system",
                        content=line_str,
                        raw={"raw_line": line_str},
                    )

            # Wait for process to complete
            await process.wait()
            logger.info(f"Process exited with code: {process.returncode}")

            # Check for errors
            if process.returncode != 0:
                stderr = await process.stderr.read()
                stderr_str = stderr.decode("utf-8")
                logger.error(f"Process error: {stderr_str}")
                yield AgentMessage(
                    type="error",
                    content=f"Process exited with code {process.returncode}: {stderr_str}",
                    raw={"stderr": stderr_str, "code": process.returncode},
                )

        finally:
            self._processes.pop(conversation_id, None)
            if process.returncode is None:
                try:
                    process.send_signal(signal.SIGTERM)
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
            logger.info(f"Cleaned up conversation {conversation_id}")

    def _parse_event(self, event: dict) -> Optional[AgentMessage]:
        event_type = event.get("type")

        if event_type == "assistant":
            # Extract content from assistant message
            message = event.get("message", {})
            content_blocks = message.get("content", [])

            messages = []
            for block in content_blocks:
                block_type = block.get("type")

                if block_type == "text":
                    text = block.get("text", "").strip()
                    if text:
                        messages.append(
                            AgentMessage(
                                type="assistant",
                                content=text,
                                raw=event,
                            )
                        )

                elif block_type == "tool_use":
                    messages.append(
                        AgentMessage(
                            type="tool_use",
                            content={
                                "tool": block.get("name"),
                                "input": block.get("input"),
                            },
                            raw=event,
                        )
                    )

            # Return first message (we'll handle multiple in the caller if needed)
            if messages:
                return messages[0]

        elif event_type == "tool_use":
            # Standalone tool_use event (fallback)
            return AgentMessage(
                type="tool_use",
                content={
                    "tool": event.get("tool") or event.get("name"),
                    "input": event.get("input"),
                },
                raw=event,
            )

        elif event_type == "tool_result":
            return AgentMessage(
                type="tool_result",
                content={
                    "tool": event.get("tool"),
                    "output": event.get("output"),
                },
                raw=event,
            )

        elif event_type == "user":
            # User messages often contain tool_results
            message = event.get("message", {})
            content_blocks = message.get("content", [])

            for block in content_blocks:
                if block.get("type") == "tool_result":
                    result_content = block.get("content", "")
                    return AgentMessage(
                        type="tool_result",
                        content={
                            "tool": block.get("tool_use_id", "")[:8],
                            "output": result_content,
                        },
                        raw=event,
                    )
            return None  # Ignore other user messages

        elif event_type == "system":
            return AgentMessage(
                type="system",
                content=event.get("message") or event.get("subtype"),
                raw=event,
            )

        elif event_type == "error":
            return AgentMessage(
                type="error",
                content=event.get("message") or str(event),
                raw=event,
            )

        elif event_type == "result":
            # Final result message - preserve usage info if present
            raw = dict(event)
            if "usage" in event:
                raw["usage"] = event["usage"]
            return AgentMessage(
                type="system",
                content=f"Completed: {event.get('subtype', 'done')}",
                raw=raw,
            )

        return None

    async def cancel(self, conversation_id: str) -> bool:
        process = self._processes.get(conversation_id)
        if not process:
            return False

        try:
            process.send_signal(signal.SIGTERM)
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            process.kill()

        self._processes.pop(conversation_id, None)
        return True

    @property
    def _running(self) -> set[str]:
        return {conv_id for conv_id, process in self._processes.items() if process.returncode is None}

    def is_running(self, conversation_id: str) -> bool:
        process = self._processes.get(conversation_id)
        return process is not None and process.returncode is None
