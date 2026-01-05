"""CLI backend - spawns claude CLI process."""

import asyncio
import json
import os
import signal
from typing import AsyncIterator, Optional

from .. import config
from .base import AgentBackend, AgentMessage


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

        # Build command
        prompt = self._build_prompt(message, history)
        cmd = [config.CLAUDE_CLI, "--output-format", "stream-json", "--verbose", "-p", prompt]

        # Add resume flag if we have a session
        if session_id:
            cmd.extend(["--resume", session_id])

        # Spawn process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(config.BASE_DIR),
        )

        self._processes[conversation_id] = process

        try:
            # Read stdout line by line
            while True:
                line = await process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                # Parse JSON event
                try:
                    event = json.loads(line_str)
                    agent_msg = self._parse_event(event)
                    if agent_msg:
                        yield agent_msg
                except json.JSONDecodeError:
                    # Non-JSON output, emit as system message
                    yield AgentMessage(
                        type="system",
                        content=line_str,
                        raw={"raw_line": line_str},
                    )

            # Wait for process to complete
            await process.wait()

            # Check for errors
            if process.returncode != 0:
                stderr = await process.stderr.read()
                yield AgentMessage(
                    type="error",
                    content=f"Process exited with code {process.returncode}",
                    raw={"stderr": stderr.decode("utf-8"), "code": process.returncode},
                )

        finally:
            self._processes.pop(conversation_id, None)

    def _parse_event(self, event: dict) -> Optional[AgentMessage]:
        """Parse a stream-json event into an AgentMessage."""
        event_type = event.get("type")

        if event_type == "assistant":
            # Extract text content from assistant message
            message = event.get("message", {})
            content_blocks = message.get("content", [])
            text_parts = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

            if text_parts:
                return AgentMessage(
                    type="assistant",
                    content="\n".join(text_parts),
                    raw=event,
                )

        elif event_type == "tool_use":
            return AgentMessage(
                type="tool_use",
                content={
                    "tool": event.get("tool"),
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

    def is_running(self, conversation_id: str) -> bool:
        """Check if a conversation is currently running."""
        process = self._processes.get(conversation_id)
        return process is not None and process.returncode is None
