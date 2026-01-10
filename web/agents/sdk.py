"""SDK backend - uses Claude Agent SDK for programmatic agent control."""

import logging
import os
from typing import AsyncIterator, Optional

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    SystemMessage,
    ResultMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from .. import config
from .base import AgentBackend, AgentMessage

logger = logging.getLogger(__name__)


class SDKBackend(AgentBackend):
    """
    Agent backend using the Claude Agent SDK.

    The SDK handles the agent loop automatically - we just need to:
    1. Send prompts via query()
    2. Stream back normalized AgentMessage objects
    3. Track sessions for conversation resumption
    """

    def __init__(self):
        self._sessions: dict[str, str] = {}  # conversation_id -> session_id
        self._running: set[str] = set()

    async def send_message(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentMessage]:
        """Send message via SDK and yield streaming responses."""

        self._running.add(conversation_id)

        try:
            # Build options
            # WebFetch/WebSearch disabled for security - use curl for allowed domains
            options = ClaudeAgentOptions(
                allowed_tools=["Skill", "Read", "Bash", "Grep", "Glob", "Write", "Edit"],
                cwd=str(config.BASE_DIR),
                permission_mode="acceptEdits",  # Auto-approve for web use
                setting_sources=["project"],  # Load project skills
            )

            # Add system prompt from AGENTS.md
            agents_md_path = config.BASE_DIR / "AGENTS.md"
            if agents_md_path.exists():
                options.system_prompt = agents_md_path.read_text()

            # Resume session if available
            resume_id = session_id or self._sessions.get(conversation_id)
            if resume_id:
                options.resume = resume_id
                logger.info(f"Resuming session {resume_id}")

            # If no session but we have history, include it in the prompt
            full_prompt = message
            if not resume_id and history:
                # Truncate very long history to avoid token limits
                MAX_HISTORY_CHARS = 50000
                history_parts = []
                total_chars = 0
                for m in history:
                    content = m['content']
                    if total_chars + len(content) > MAX_HISTORY_CHARS:
                        # Truncate this message
                        remaining = MAX_HISTORY_CHARS - total_chars
                        if remaining > 500:
                            content = content[:remaining] + "\n[... truncated ...]"
                            history_parts.append(f"{'User' if m['role'] == 'user' else 'Assistant'}: {content}")
                        break
                    history_parts.append(f"{'User' if m['role'] == 'user' else 'Assistant'}: {content}")
                    total_chars += len(content)

                if history_parts:
                    history_text = "\n\n".join(history_parts)
                    full_prompt = f"""Previous conversation context:

{history_text}

---

User: {message}"""
                    logger.info(f"No session, prepending {len(history_parts)} messages ({total_chars} chars) as context")
            else:
                full_prompt = message

            logger.info(f"Starting SDK query for conversation {conversation_id}")

            # Stream responses from SDK
            async for sdk_message in query(prompt=full_prompt, options=options):
                # Capture session ID from system init message
                if isinstance(sdk_message, SystemMessage):
                    if hasattr(sdk_message, 'session_id') and sdk_message.session_id:
                        self._sessions[conversation_id] = sdk_message.session_id
                        logger.info(f"Captured session ID: {sdk_message.session_id}")

                # Normalize and yield messages
                for agent_msg in self._normalize_message(sdk_message):
                    yield agent_msg

            logger.info(f"SDK query completed for conversation {conversation_id}")

        except Exception as e:
            error_str = str(e)
            logger.error(f"SDK error: {error_str}")

            # If session resume failed, try without resume
            if "exit code 1" in error_str and resume_id:
                logger.warning(f"Session resume may have failed, retrying without session")
                try:
                    options.resume = None
                    async for sdk_message in query(prompt=full_prompt, options=options):
                        if isinstance(sdk_message, SystemMessage):
                            if hasattr(sdk_message, 'session_id') and sdk_message.session_id:
                                self._sessions[conversation_id] = sdk_message.session_id
                        for agent_msg in self._normalize_message(sdk_message):
                            yield agent_msg
                    return
                except Exception as retry_error:
                    logger.error(f"Retry also failed: {retry_error}")
                    error_str = str(retry_error)

            yield AgentMessage(
                type="error",
                content=error_str,
                raw={"error": error_str, "type": type(e).__name__}
            )

        finally:
            self._running.discard(conversation_id)

    def _normalize_message(self, sdk_message) -> list[AgentMessage]:
        """Convert SDK message to our normalized AgentMessage format."""
        messages = []

        if isinstance(sdk_message, AssistantMessage):
            # AssistantMessage has content blocks
            for block in sdk_message.content:
                if isinstance(block, TextBlock):
                    if block.text.strip():
                        messages.append(AgentMessage(
                            type="assistant",
                            content=block.text,
                            raw={"block_type": "text"}
                        ))

                elif isinstance(block, ToolUseBlock):
                    messages.append(AgentMessage(
                        type="tool_use",
                        content={
                            "tool": block.name,
                            "input": block.input,
                        },
                        raw={"block_type": "tool_use", "id": block.id}
                    ))

        elif isinstance(sdk_message, UserMessage):
            # UserMessage may contain tool results
            for block in sdk_message.content:
                if isinstance(block, ToolResultBlock):
                    messages.append(AgentMessage(
                        type="tool_result",
                        content={
                            "tool": getattr(block, 'tool_use_id', '')[:8],
                            "output": block.content if hasattr(block, 'content') else str(block),
                        },
                        raw={"block_type": "tool_result"}
                    ))

        elif isinstance(sdk_message, SystemMessage):
            subtype = getattr(sdk_message, 'subtype', None)
            data = getattr(sdk_message, 'data', {}) or {}
            message_content = getattr(sdk_message, 'message', None) or subtype or 'system'
            messages.append(AgentMessage(
                type="system",
                content=message_content,
                raw={
                    "subtype": subtype,
                    "session_id": data.get('session_id'),
                    "data": data,
                }
            ))

        elif isinstance(sdk_message, ResultMessage):
            messages.append(AgentMessage(
                type="system",
                content=f"Completed: {getattr(sdk_message, 'subtype', 'done')}",
                raw={"result": True}
            ))

        return messages

    async def cancel(self, conversation_id: str) -> bool:
        """Cancel a running conversation."""
        if conversation_id in self._running:
            self._running.discard(conversation_id)
            # Note: SDK doesn't have explicit cancel - process will complete
            # For true cancellation, would need to track the async task
            return True
        return False

    def is_running(self, conversation_id: str) -> bool:
        """Check if a conversation is currently running."""
        return conversation_id in self._running
