"""Ollama backend - streams responses from a self-hosted Ollama server."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date
from typing import AsyncIterator, Optional

import httpx

from .. import config
from .base import AgentBackend, AgentMessage
from .ollama_tools import execute_tool, parse_tool_call, tool_protocol

logger = logging.getLogger(__name__)

_TOOL_RESULT_PREFIX = "TOOL_RESULT"
_MAX_CONSECUTIVE_JSON_ERRORS = 5


class OllamaBackend(AgentBackend):
    """Agent backend using a self-hosted Ollama HTTP API."""

    def __init__(self) -> None:
        self._running: set[str] = set()
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._client = httpx.AsyncClient(timeout=config.OLLAMA_REQUEST_TIMEOUT)
        self._client_lock = asyncio.Lock()
        self._last_usage: Optional[dict] = None

    async def send_message(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentMessage]:
        """Send a message via Ollama and yield streaming responses."""
        cancel_event = asyncio.Event()
        self._cancel_events[conversation_id] = cancel_event
        self._running.add(conversation_id)

        # Emit init event (parity with SDK SystemMessage)
        ollama_session = session_id or conversation_id
        yield AgentMessage(
            type="system",
            content="init",
            raw={
                "subtype": "init",
                "session_id": ollama_session,
                "data": {"session_id": ollama_session},
            },
        )

        try:
            async for event in self._run_chat(message, history, cancel_event):
                yield event
        except httpx.ConnectError:
            await self._reset_client()
            logger.error("Ollama connection failed, client reset")
            yield AgentMessage(
                type="error",
                content="Cannot connect to Ollama server",
                raw={"error": "connection_failed"},
            )
        except httpx.ReadTimeout:
            await self._reset_client()
            logger.error("Ollama read timeout, client reset")
            yield AgentMessage(
                type="error",
                content="Ollama request timed out",
                raw={"error": "timeout"},
            )
        except Exception as exc:
            logger.error(f"Ollama backend error: {exc}")
            yield AgentMessage(
                type="error",
                content=str(exc),
                raw={"error": str(exc)},
            )
        finally:
            self._running.discard(conversation_id)
            self._cancel_events.pop(conversation_id, None)

    async def _run_chat(
        self,
        message: str,
        history: list[dict],
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[AgentMessage]:
        messages = self._build_messages(message, history)

        max_steps = max(1, config.OLLAMA_TOOL_MAX_STEPS)
        for _ in range(max_steps):
            if cancel_event.is_set():
                yield AgentMessage(type="system", content="Cancelled", raw={"cancelled": True})
                return

            assistant_text = ""
            did_stream = False

            if config.OLLAMA_STREAM:
                buffer = ""
                should_stream: Optional[bool] = None
                chunk_size = config.OLLAMA_STREAM_CHUNK_SIZE

                async for chunk in self._stream_chat(messages, cancel_event):
                    assistant_text += chunk

                    if should_stream is None:
                        should_stream = _should_stream_text(assistant_text)
                        if should_stream is None:
                            continue

                        if should_stream:
                            buffer = assistant_text
                            if _should_flush_buffer(buffer, chunk_size):
                                did_stream = True
                                yield AgentMessage(
                                    type="assistant",
                                    content=buffer,
                                    raw={"append": True},
                                )
                                buffer = ""
                            continue

                    if should_stream:
                        buffer += chunk
                        # Stop streaming if a tool-call pattern appears
                        if _looks_like_tool_start(buffer):
                            should_stream = False
                            continue
                        if _should_flush_buffer(buffer, chunk_size):
                            did_stream = True
                            yield AgentMessage(
                                type="assistant",
                                content=buffer,
                                raw={"append": True},
                            )
                            buffer = ""

                if cancel_event.is_set():
                    yield AgentMessage(type="system", content="Cancelled", raw={"cancelled": True})
                    return
                if should_stream and buffer:
                    # Final flush — but not if it looks like a tool call
                    if not _looks_like_tool_start(buffer):
                        did_stream = True
                        yield AgentMessage(
                            type="assistant",
                            content=buffer,
                            raw={"append": True},
                        )
            else:
                assistant_text = await self._chat_once(messages)

            tool_call = parse_tool_call(assistant_text)
            if tool_call:
                tool_name, tool_input = tool_call
                tool_use_id = f"ollama_{uuid.uuid4().hex[:12]}"

                yield AgentMessage(
                    type="tool_use",
                    content={"tool": tool_name, "input": tool_input},
                    raw={"block_type": "tool_use", "id": tool_use_id},
                )

                output = await asyncio.to_thread(execute_tool, tool_name, tool_input)

                yield AgentMessage(
                    type="tool_result",
                    content={
                        "tool": tool_name,
                        "output": output,
                    },
                    raw={"block_type": "tool_result", "tool_use_id": tool_use_id},
                )

                messages.append({"role": "assistant", "content": assistant_text})
                messages.append({
                    "role": "user",
                    "content": f"{_TOOL_RESULT_PREFIX} [{tool_use_id}] {tool_name}:\n{output}",
                })
                continue

            if not did_stream:
                yield AgentMessage(type="assistant", content=assistant_text)
            # Emit final result event with usage (parity with SDK ResultMessage)
            raw: dict = {"result": True}
            if self._last_usage:
                raw["usage"] = self._last_usage
            yield AgentMessage(
                type="system",
                content="Completed: done",
                raw=raw,
            )
            return

        yield AgentMessage(
            type="error",
            content="Tool loop exceeded maximum steps",
            raw={"tool_steps": max_steps},
        )

    async def _chat_once(self, messages: list[dict]) -> str:
        url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": self._build_options(),
        }

        client = await self._ensure_client()
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        self._last_usage = {
            "input_tokens": data.get("prompt_eval_count", 0),
            "output_tokens": data.get("eval_count", 0),
        }

        message = data.get("message") or {}
        content = message.get("content", "")
        return content.strip()

    async def _stream_chat(
        self,
        messages: list[dict],
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[str]:
        url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": self._build_options(),
        }

        client = await self._ensure_client()
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            consecutive_errors = 0
            async for line in response.aiter_lines():
                if cancel_event.is_set():
                    return
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    consecutive_errors = 0
                except json.JSONDecodeError:
                    consecutive_errors += 1
                    logger.warning("Malformed JSON in Ollama stream (%d): %s", consecutive_errors, line[:200])
                    if consecutive_errors >= _MAX_CONSECUTIVE_JSON_ERRORS:
                        raise RuntimeError(f"Ollama stream corrupted: {consecutive_errors} consecutive malformed lines")
                    continue

                if "error" in data:
                    raise RuntimeError(data["error"])

                message = data.get("message") or {}
                content = message.get("content")
                if content:
                    yield content

                if data.get("done"):
                    self._last_usage = {
                        "input_tokens": data.get("prompt_eval_count", 0),
                        "output_tokens": data.get("eval_count", 0),
                    }
                    return

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Return the shared client, recreating it if closed."""
        if self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=config.OLLAMA_REQUEST_TIMEOUT)
        return self._client

    async def _reset_client(self) -> None:
        """Close and recreate the client after a connection failure."""
        async with self._client_lock:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = httpx.AsyncClient(timeout=config.OLLAMA_REQUEST_TIMEOUT)

    def _build_options(self) -> dict:
        options: dict = {"temperature": config.OLLAMA_TEMPERATURE}
        if config.OLLAMA_NUM_CTX > 0:
            options["num_ctx"] = config.OLLAMA_NUM_CTX
        return options

    def _build_messages(self, message: str, history: list[dict]) -> list[dict]:
        system_prompt = self._load_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]

        trimmed_history = _trim_history(history, config.OLLAMA_MAX_HISTORY_CHARS)
        messages.extend(trimmed_history)
        messages.append({"role": "user", "content": message})
        return messages

    def _load_system_prompt(self) -> str:
        agents_md_path = config.BASE_DIR / "AGENTS.md"
        agents_content = agents_md_path.read_text() if agents_md_path.exists() else ""
        today = date.today().strftime("%A %d %B %Y")
        header = f"Aujourd'hui, nous sommes le {today}."
        protocol = tool_protocol()
        return f"{header}\n\n{agents_content}\n\n{protocol}"

    async def cancel(self, conversation_id: str) -> bool:
        """Cancel a running conversation."""
        event = self._cancel_events.get(conversation_id)
        if event is None:
            return False
        event.set()
        return True

    def is_running(self, conversation_id: str) -> bool:
        """Check if a conversation is currently running."""
        return conversation_id in self._running


def _trim_history(history: list[dict], max_chars: int) -> list[dict]:
    if max_chars <= 0:
        return []

    total = 0
    trimmed = []
    for msg in reversed(history):
        content = msg.get("content", "")
        msg_len = len(content)
        if total + msg_len > max_chars:
            # If nothing kept yet, include this message truncated to fit
            if not trimmed:
                content = content[:max_chars]
                trimmed.append({"role": msg.get("role", "user"), "content": content})
            break
        total += msg_len
        trimmed.append({"role": msg.get("role", "user"), "content": content})
    return list(reversed(trimmed))


def _should_stream_text(text: str) -> Optional[bool]:
    """Decide whether to stream text incrementally.

    Returns None while undecided (whitespace only), False for JSON/code-fence
    (buffer the whole thing), True for prose (stream incrementally).
    Caps the undecided window at 32 chars to avoid buffering forever.
    """
    stripped = text.lstrip()
    if not stripped:
        # Still only whitespace — cap the undecided window
        if len(text) > 32:
            return True
        return None
    first = stripped[0]
    if first in ("{", "`"):
        return False
    return True


def _looks_like_tool_start(buffer: str) -> bool:
    """Detect a probable tool-call JSON forming in the streaming buffer.

    Checks for code fences (```json) or a raw JSON object on its own line
    that starts with {"tool". Called mid-stream to stop flushing prose once
    the model begins emitting a tool call.
    """
    if "```" in buffer:
        return True
    # Raw JSON on its own line: \n{"tool...
    idx = buffer.rfind("\n{")
    if idx >= 0 and '"tool"' in buffer[idx:]:
        return True
    return False


def _should_flush_buffer(buffer: str, chunk_size: int) -> bool:
    if not buffer:
        return False
    if chunk_size <= 0:
        return True
    return len(buffer) >= chunk_size
