"""SDK backend — uses claude_agent_sdk.query() instead of raw subprocess."""

import asyncio
import logging
import os
from typing import AsyncIterator, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)
from claude_agent_sdk._errors import ProcessError

from .. import config
from .base import AgentBackend, AgentMessage, build_system_prompt

logger = logging.getLogger(__name__)


class SDKBackend(AgentBackend):
    """Agent backend using the Claude Agent SDK (query + resume)."""

    def __init__(self):
        self._cancel_events: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # Prompt construction (same as CLIBackend)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(message: str, history: list[dict]) -> str:
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

    # ------------------------------------------------------------------
    # SDK options construction
    # ------------------------------------------------------------------

    def _build_options(self, conversation_id: str, session_id: Optional[str]) -> ClaudeAgentOptions:
        system_prompt = build_system_prompt()

        # Permissions
        if os.getenv("CONTAINER_ENV"):
            permission_mode = "bypassPermissions"
            allowed_tools = []
        elif config.ALLOWED_TOOLS:
            permission_mode = "default"
            allowed_tools = [t.strip() for t in config.ALLOWED_TOOLS.split(",") if t.strip()]
        else:
            permission_mode = "default"
            allowed_tools = []

        # Env: strip ANTHROPIC_API_KEY (override with empty string so
        # CLAUDE_CODE_OAUTH_TOKEN from os.environ is used for auth).
        env = {
            "ANTHROPIC_API_KEY": "",
            "MATOMETA_CONVERSATION_ID": conversation_id,
        }

        return ClaudeAgentOptions(
            system_prompt=system_prompt,
            permission_mode=permission_mode,
            allowed_tools=allowed_tools,
            resume=session_id,
            cwd=str(config.BASE_DIR),
            cli_path=config.CLAUDE_CLI,
            add_dirs=list(config.ADDITIONAL_DIRS),
            setting_sources=["project"],
            env=env,
            max_buffer_size=10 * 1024 * 1024,
        )

    # ------------------------------------------------------------------
    # Main interface
    # ------------------------------------------------------------------

    async def send_message(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentMessage]:
        if not session_id:
            async for msg in self._run_sdk(conversation_id, message, history, None):
                yield msg
            return

        # Try with session first, retry without on failure
        retry_without_session = False
        had_useful_output = False

        async for msg in self._run_sdk(conversation_id, message, history, session_id):
            if msg.type == "error":
                error_str = str(msg.content)
                if "tool_use ids must be unique" in error_str:
                    logger.warning(f"Session {session_id} corrupted (duplicate IDs), retrying without resume")
                    retry_without_session = True
                    break
                if not had_useful_output:
                    logger.warning(f"Session {session_id} failed (no output), retrying without resume")
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
            async for msg in self._run_sdk(conversation_id, message, history, None):
                yield msg

    # ------------------------------------------------------------------
    # Internal: call query()
    # ------------------------------------------------------------------

    async def _run_sdk(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str],
    ) -> AsyncIterator[AgentMessage]:
        if session_id:
            prompt = message
        else:
            prompt = self._build_prompt(message, history)

        options = self._build_options(conversation_id, session_id)
        cancel_event = asyncio.Event()
        self._cancel_events[conversation_id] = cancel_event

        logger.info(
            f"Starting SDK query (prompt length: {len(prompt)}, session: {session_id or 'none'})"
        )

        try:
            async for sdk_msg in query(prompt=prompt, options=options):
                if cancel_event.is_set():
                    break
                for agent_msg in self._translate_message(sdk_msg):
                    yield agent_msg
        except ProcessError as e:
            logger.error(f"SDK ProcessError: {e} (exit_code={e.exit_code})")
            yield AgentMessage(
                type="error",
                content=f"Process exited with code {e.exit_code}: {e.stderr or e}",
                raw={"stderr": e.stderr, "code": e.exit_code},
            )
        except Exception as e:
            logger.exception(f"SDK error for {conversation_id}")
            yield AgentMessage(type="error", content=str(e), raw={})
        finally:
            self._cancel_events.pop(conversation_id, None)
            logger.info(f"SDK query finished for {conversation_id}")

    # ------------------------------------------------------------------
    # Message translation
    # ------------------------------------------------------------------

    @staticmethod
    def _translate_message(sdk_msg) -> list[AgentMessage]:
        """Convert an SDK message to zero or more AgentMessages."""
        msgs: list[AgentMessage] = []

        if isinstance(sdk_msg, AssistantMessage):
            for block in sdk_msg.content:
                if isinstance(block, TextBlock):
                    text = block.text.strip()
                    if text:
                        msgs.append(AgentMessage(type="assistant", content=text, raw={}))
                elif isinstance(block, ToolUseBlock):
                    msgs.append(
                        AgentMessage(
                            type="tool_use",
                            content={"tool": block.name, "input": block.input},
                            raw={},
                        )
                    )

        elif isinstance(sdk_msg, SystemMessage):
            raw = {"subtype": sdk_msg.subtype, **sdk_msg.data}
            msgs.append(AgentMessage(type="system", content=sdk_msg.subtype, raw=raw))

        elif isinstance(sdk_msg, ResultMessage):
            raw = {"subtype": sdk_msg.subtype, "type": "result", "session_id": sdk_msg.session_id}
            if sdk_msg.usage:
                raw["usage"] = sdk_msg.usage
            if sdk_msg.total_cost_usd is not None:
                raw["total_cost_usd"] = sdk_msg.total_cost_usd
            msgs.append(
                AgentMessage(
                    type="system",
                    content=f"Completed: {sdk_msg.subtype}",
                    raw=raw,
                )
            )

        # UserMessage (tool results) — pass through for PM to see tool_result events
        else:
            # Check if it's a UserMessage with tool results
            content = getattr(sdk_msg, "content", None)
            if isinstance(content, list):
                for block in content:
                    tool_use_id = getattr(block, "tool_use_id", None)
                    if tool_use_id:
                        block_content = getattr(block, "content", "")
                        msgs.append(
                            AgentMessage(
                                type="tool_result",
                                content={"tool": tool_use_id[:8], "output": block_content},
                                raw={},
                            )
                        )

        return msgs

    # ------------------------------------------------------------------
    # Cancellation & status
    # ------------------------------------------------------------------

    async def cancel(self, conversation_id: str) -> bool:
        event = self._cancel_events.get(conversation_id)
        if event:
            event.set()
            return True
        return False

    def is_running(self, conversation_id: str) -> bool:
        return conversation_id in self._cancel_events
