"""CLI backend - spawns claude CLI process."""

import asyncio
import json
import logging
import os
import signal
from typing import AsyncIterator, Optional

from .. import config
from .base import AgentBackend, AgentMessage

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class CLIBackend(AgentBackend):
    """Agent backend that spawns the claude CLI."""

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def _build_prompt(self, message: str, history: list[dict]) -> str:
        """Build a prompt including conversation history."""
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
        """Spawn claude CLI and stream responses."""

        # Build command with system context
        prompt = self._build_prompt(message, history)

        cmd = [
            config.CLAUDE_CLI,
            "--output-format", "stream-json",
            "--verbose",
            "--setting-sources", "project",  # Only load project skills, not user plugins
        ]

        # Add AGENTS.md as system prompt
        agents_md_path = config.BASE_DIR / "AGENTS.md"
        if agents_md_path.exists():
            agents_content = agents_md_path.read_text()
            cmd.extend(["--system-prompt", agents_content])

        # Whitelist safe tools only
        if config.ALLOWED_TOOLS:
            cmd.extend(["--allowedTools", config.ALLOWED_TOOLS])

        cmd.extend(["-p", prompt])

        # Add resume flag if we have a session
        if session_id:
            cmd.extend(["--resume", session_id])

        logger.info(f"Starting claude CLI: {' '.join(cmd[:4])}... (prompt length: {len(prompt)})")

        # Build environment: inherit from parent but remove ANTHROPIC_API_KEY
        # so CLI uses OAuth credentials instead
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

        # Spawn process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.BASE_DIR),
            env=env,
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
                logger.debug(f"Line {line_count}: {line_str[:100]}...")

                # Parse JSON event
                try:
                    event = json.loads(line_str)
                    agent_msg = self._parse_event(event)
                    if agent_msg:
                        logger.debug(f"Parsed event: {agent_msg.type}")
                        yield agent_msg
                except json.JSONDecodeError:
                    # Non-JSON output, emit as system message
                    logger.warning(f"Non-JSON line: {line_str[:100]}")
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
                    content=f"Process exited with code {process.returncode}",
                    raw={"stderr": stderr_str, "code": process.returncode},
                )

        finally:
            self._processes.pop(conversation_id, None)
            logger.info(f"Cleaned up conversation {conversation_id}")

    def _parse_event(self, event: dict) -> Optional[AgentMessage]:
        """Parse a stream-json event into an AgentMessage."""
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
                        messages.append(AgentMessage(
                            type="assistant",
                            content=text,
                            raw=event,
                        ))

                elif block_type == "tool_use":
                    messages.append(AgentMessage(
                        type="tool_use",
                        content={
                            "tool": block.get("name"),
                            "input": block.get("input"),
                        },
                        raw=event,
                    ))

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
            # Final result message
            return AgentMessage(
                type="system",
                content=f"Completed: {event.get('subtype', 'done')}",
                raw=event,
            )

        return None

    async def cancel(self, conversation_id: str) -> bool:
        """Cancel a running conversation."""
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
        """Get set of currently running conversation IDs."""
        return {
            conv_id
            for conv_id, process in self._processes.items()
            if process.returncode is None
        }

    def is_running(self, conversation_id: str) -> bool:
        """Check if a conversation is currently running."""
        process = self._processes.get(conversation_id)
        return process is not None and process.returncode is None
