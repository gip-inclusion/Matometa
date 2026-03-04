"""Process Manager: runs agents, persists events to database.

Runs in-process as an asyncio task via FastAPI lifespan (web/app.py).
Communicates with the SSE handler via in-memory signals (web/signals.py)
and the pm_commands table (input).
"""

import asyncio
import json
import logging
import os

from lib.api_signals import parse_api_signals
from lib.tool_taxonomy import classify_tool

from . import config
from .agents import get_agent
from .agents.base import AgentBackend
from .audit import audit_log
from .signals import signals
from .storage import store

logger = logging.getLogger(__name__)


MAX_CONCURRENT_AGENTS = int(os.environ.get("MAX_CONCURRENT_AGENTS", "2"))


class ProcessManager:
    def __init__(self):
        self.backend: AgentBackend = get_agent()
        self.running: dict[str, asyncio.Task] = {}
        self._queued: list[tuple[str, dict]] = []  # (conv_id, payload) waiting for a slot

    async def run(self):
        """Main loop: poll for commands, execute them."""
        cleared_ids = await asyncio.to_thread(store.clear_all_needs_response)
        if cleared_ids:
            for conv_id in cleared_ids:
                store.add_message(conv_id, "assistant", "*Interrompu (redémarrage serveur).*")
            logger.info(f"Cleared {len(cleared_ids)} stuck needs_response flags on startup")
        logger.info(f"Process manager started (max_concurrent={MAX_CONCURRENT_AGENTS})")
        await asyncio.to_thread(store.update_pm_heartbeat)
        signals.update_pm_alive()
        heartbeat_counter = 0
        HEARTBEAT_EVERY = 10  # 10 x 0.5s = 5s
        while True:
            try:
                heartbeat_counter += 1
                if heartbeat_counter >= HEARTBEAT_EVERY:
                    await asyncio.to_thread(store.update_pm_heartbeat)
                    signals.update_pm_alive()
                    heartbeat_counter = 0

                # Drain finished tasks and start queued ones
                self._reap_finished()
                self._start_queued()

                commands = await asyncio.to_thread(store.claim_pending_pm_commands)
                for cmd in commands:
                    if cmd["command"] == "run":
                        conv_id = cmd["conversation_id"]
                        if conv_id in self.running:
                            logger.warning(f"Agent already running for {conv_id}, skipping")
                        elif len(self.running) < MAX_CONCURRENT_AGENTS:
                            self._start_agent(conv_id, cmd["payload"])
                        else:
                            logger.info(
                                f"Agent queued for {conv_id} ({len(self.running)} running, {len(self._queued)} queued)"
                            )
                            self._queued.append((conv_id, cmd["payload"]))
                    elif cmd["command"] == "cancel":
                        # Also remove from queue if waiting
                        self._queued = [(c, p) for c, p in self._queued if c != cmd["conversation_id"]]
                        await self._cancel_agent(cmd["conversation_id"])
            except Exception:
                logger.exception("Error polling pm_commands")
            await asyncio.sleep(0.5)

    def _start_agent(self, conv_id: str, payload: dict):
        task = asyncio.create_task(self._run_agent(conv_id, payload))
        self.running[conv_id] = task

    def _reap_finished(self):
        """Remove completed tasks from running dict."""
        done = [cid for cid, t in self.running.items() if t.done()]
        for cid in done:
            self.running.pop(cid, None)

    def _start_queued(self):
        """Start queued agents if slots are available."""
        while self._queued and len(self.running) < MAX_CONCURRENT_AGENTS:
            conv_id, payload = self._queued.pop(0)
            if conv_id in self.running:
                continue
            logger.info(f"Starting queued agent for {conv_id}")
            self._start_agent(conv_id, payload)

    async def _run_agent(self, conversation_id: str, payload: dict):
        """Run agent for a conversation, persist all events to DB."""
        prompt = payload["prompt"]
        history = payload.get("history", [])
        session_id = payload.get("session_id")
        user_email = payload.get("user_email")

        assistant_text_parts: list[str] = []
        assistant_msg_id: int | None = None

        try:
            async for event in self.backend.send_message(
                conversation_id=conversation_id,
                message=prompt,
                history=history,
                session_id=session_id,
            ):
                if event.type == "assistant":
                    assistant_text_parts.append(str(event.content))
                    append_mode = bool(getattr(event, "raw", {}).get("append"))
                    full_text = "".join(assistant_text_parts) if append_mode else "\n".join(assistant_text_parts)
                    if assistant_msg_id is None:
                        msg = store.add_message(conversation_id, "assistant", full_text)
                        assistant_msg_id = msg.id if msg else None
                    else:
                        store.update_message(assistant_msg_id, full_text)
                    signals.notify_message(conversation_id)

                elif event.type in ("tool_use", "tool_result"):
                    if event.type == "tool_use":
                        assistant_msg_id = None
                        assistant_text_parts = []
                    content = self._serialize_tool_event(event, conversation_id, user_email)
                    store.add_message(conversation_id, event.type, content)
                    signals.notify_message(conversation_id)

                elif event.type == "system":
                    if event.raw.get("subtype") == "init":
                        new_session_id = event.raw.get("session_id")
                        if new_session_id:
                            store.update_conversation(conversation_id, session_id=new_session_id)
                    if event.raw.get("usage"):
                        self._persist_usage(conversation_id, event.raw["usage"])

        except Exception:
            logger.exception(f"Agent error for {conversation_id}")
        finally:
            store.update_conversation(conversation_id, needs_response=False)
            signals.notify_finished(conversation_id)
            self.running.pop(conversation_id, None)
            logger.info(f"Agent finished for {conversation_id}")

    def _serialize_tool_event(self, event, conversation_id: str, user_email: str | None) -> str:
        """Serialize a tool_use or tool_result event for DB storage."""
        if event.type == "tool_use" and isinstance(event.content, dict):
            tool_name = event.content.get("tool", "")
            tool_input = event.content.get("input", {})
            category = classify_tool(tool_name, tool_input)
            enriched = {**event.content, "category": category}

            audit_log(
                conversation_id=conversation_id,
                user_email=user_email or "",
                tool_name=tool_name,
                tool_input=tool_input,
            )
            return json.dumps(enriched)

        elif event.type == "tool_result":
            if isinstance(event.content, dict) and "output" in event.content:
                raw_content = event.content["output"]
                if not isinstance(raw_content, str):
                    raw_content = str(raw_content)
            elif isinstance(event.content, str):
                raw_content = event.content
            else:
                raw_content = str(event.content)

            api_calls = parse_api_signals(raw_content)
            if api_calls:
                enriched = {"output": event.content, "api_calls": api_calls}
                return json.dumps(enriched)

        return json.dumps(event.content) if isinstance(event.content, dict) else str(event.content)

    def _persist_usage(self, conversation_id: str, usage: dict):
        """Persist token usage from a result event."""
        extra = {}
        if usage.get("service_tier"):
            extra["service_tier"] = usage["service_tier"]
        if usage.get("web_search_requests"):
            extra["web_search_requests"] = usage["web_search_requests"]

        store.accumulate_usage(
            conversation_id,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            backend=config.AGENT_BACKEND,
            extra=extra if extra else None,
        )

    async def _cancel_agent(self, conversation_id: str):
        """Cancel a running agent task."""
        task = self.running.get(conversation_id)
        if task:
            await self.backend.cancel(conversation_id)
            self.running.pop(conversation_id, None)
            logger.info(f"Cancelled agent for {conversation_id}")

    def is_running(self, conversation_id: str) -> bool:
        """Check if an agent is running for a conversation."""
        task = self.running.get(conversation_id)
        return task is not None and not task.done()
