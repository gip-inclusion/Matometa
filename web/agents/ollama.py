"""Ollama backend - streams responses from a self-hosted Ollama server."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import AsyncIterator, Optional

import httpx

from .. import config
from .base import AgentBackend, AgentMessage
from .ollama_tools import execute_tool, parse_tool_call, tool_protocol

logger = logging.getLogger(__name__)


class OllamaBackend(AgentBackend):
    """Agent backend using a self-hosted Ollama HTTP API."""

    def __init__(self) -> None:
        self._running: set[str] = set()
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._system_prompt: Optional[str] = None

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

        try:
            async for event in self._run_chat(message, history, cancel_event):
                yield event
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
                yield AgentMessage(
                    type="tool_use",
                    content={"tool": tool_name, "input": tool_input},
                )

                output = await asyncio.to_thread(execute_tool, tool_name, tool_input)

                yield AgentMessage(
                    type="tool_result",
                    content={
                        "tool": tool_name,
                        "output": output,
                    },
                )

                messages.append({"role": "assistant", "content": assistant_text})
                messages.append({
                    "role": "user",
                    "content": f"TOOL_RESULT {tool_name}:\n{output}",
                })
                continue

            if not did_stream:
                yield AgentMessage(type="assistant", content=assistant_text)
            return

        yield AgentMessage(
            type="error",
            content="Tool loop exceeded maximum steps",
            raw={"tool_steps": max_steps},
        )

    async def _chat_once(self, messages: list[dict]) -> str:
        base_url = config.OLLAMA_BASE_URL.rstrip("/")
        url = f"{base_url}/api/chat"

        options = {
            "temperature": config.OLLAMA_TEMPERATURE,
        }
        if config.OLLAMA_NUM_CTX > 0:
            options["num_ctx"] = config.OLLAMA_NUM_CTX

        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        timeout = config.OLLAMA_REQUEST_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message") or {}
        content = message.get("content", "")
        return content.strip()

    async def _stream_chat(
        self,
        messages: list[dict],
        cancel_event: asyncio.Event,
    ) -> AsyncIterator[str]:
        base_url = config.OLLAMA_BASE_URL.rstrip("/")
        url = f"{base_url}/api/chat"

        options = {
            "temperature": config.OLLAMA_TEMPERATURE,
        }
        if config.OLLAMA_NUM_CTX > 0:
            options["num_ctx"] = config.OLLAMA_NUM_CTX

        payload = {
            "model": config.OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": options,
        }

        timeout = config.OLLAMA_REQUEST_TIMEOUT
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        return
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if "error" in data:
                        raise RuntimeError(data["error"])

                    message = data.get("message") or {}
                    content = message.get("content")
                    if content:
                        yield content

                    if data.get("done"):
                        return

    def _build_messages(self, message: str, history: list[dict]) -> list[dict]:
        system_prompt = self._load_system_prompt()
        messages = [{"role": "system", "content": system_prompt}]

        trimmed_history = _trim_history(history, config.OLLAMA_MAX_HISTORY_CHARS)
        messages.extend(trimmed_history)
        messages.append({"role": "user", "content": message})
        return messages

    def _load_system_prompt(self) -> str:
        if self._system_prompt is not None:
            return self._system_prompt

        agents_md_path = config.BASE_DIR / "AGENTS.md"
        agents_content = agents_md_path.read_text() if agents_md_path.exists() else ""
        today = date.today().strftime("%A %d %B %Y")
        header = f"Aujourd'hui, nous sommes le {today}."
        protocol = tool_protocol()
        self._system_prompt = f"{header}\n\n{agents_content}\n\n{protocol}"
        return self._system_prompt

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
        total += len(content)
        if total > max_chars:
            break
        trimmed.append({"role": msg.get("role", "user"), "content": content})
    return list(reversed(trimmed))


def _chunk_text(text: str, size: int) -> list[str]:
    if text == "":
        return [""]
    if size <= 0:
        return [text]
    return [text[i:i + size] for i in range(0, len(text), size)]


def _should_stream_text(text: str) -> Optional[bool]:
    stripped = text.lstrip()
    if not stripped:
        return None
    first = stripped[0]
    if first in ("{", "`"):
        return False
    return True


def _should_flush_buffer(buffer: str, chunk_size: int) -> bool:
    if not buffer:
        return False
    if chunk_size <= 0:
        return True
    return len(buffer) >= chunk_size
