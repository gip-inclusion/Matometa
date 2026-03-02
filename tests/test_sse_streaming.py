"""
Tests for SSE streaming and event storage.

Run with: pytest tests/test_sse_streaming.py -v
"""

import asyncio
import importlib
import json
import threading
import time

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Module-scoped FastAPI app with fresh database."""
    from web import database

    importlib.reload(database)
    from web import storage

    importlib.reload(storage)

    from web.app import app as fastapi_app

    yield fastapi_app

    from web.db import get_db

    with get_db() as conn:
        conn.execute_raw("""
            TRUNCATE TABLE messages, conversation_tags, report_tags,
                uploaded_files, cron_runs, pinned_items, pm_commands,
                pm_heartbeat, reports, conversations, tags, schema_version
                CASCADE;
        """)


@pytest.fixture
def client(app):
    from starlette.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def conversation(app):
    """Create a conversation with one user message awaiting response."""
    from web.signals import signals
    from web.storage import store

    store.update_pm_heartbeat()  # Simulate PM being alive
    signals.update_pm_alive()
    conv = store.create_conversation(user_id="test@example.com")
    store.add_message(conv.id, "user", "Hello agent")
    store.update_conversation(conv.id, needs_response=True)
    return conv


@pytest.fixture
def responded_conversation(app):
    """Create a conversation with a user message and an assistant response."""
    from web.storage import store

    conv = store.create_conversation(user_id="test@example.com")
    store.add_message(conv.id, "user", "Hello agent")
    store.add_message(conv.id, "assistant", "Hello! How can I help?")
    return conv


def _parse_sse_events(response_data: bytes) -> list[dict]:
    """Parse SSE event stream into a list of {event, data} dicts."""
    events = []
    current_event = None
    current_data = None

    for line in response_data.decode("utf-8").split("\n"):
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: "):
            current_data = line[6:]
        elif line == "" and current_event is not None:
            entry = {"event": current_event}
            if current_data:
                try:
                    entry["data"] = json.loads(current_data)
                except json.JSONDecodeError:
                    entry["data"] = current_data
            events.append(entry)
            current_event = None
            current_data = None

    return events


def _simulate_pm(conv_id, messages, delay=0.1):
    """Simulate the process manager writing messages then clearing needs_response.

    Runs in a background thread so the SSE handler can stream concurrently.
    Fires signals alongside DB writes (matching real PM behavior).

    Note: asyncio.Event is not thread-safe, so we use the event loop's
    call_soon_threadsafe to schedule signal notifications from this thread.
    """

    def _run():
        time.sleep(delay)
        from web.signals import signals
        from web.storage import store

        for msg_type, content in messages:
            store.add_message(
                conv_id,
                msg_type,
                content if isinstance(content, str) else json.dumps(content),
            )
            # Thread-safe signal: schedule on the event loop that owns the Event
            try:
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(signals.notify_message, conv_id)
            except RuntimeError:
                signals.notify_message(conv_id)  # fallback if no loop
        store.update_conversation(conv_id, needs_response=False)
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(signals.notify_finished, conv_id)
        except RuntimeError:
            signals.notify_finished(conv_id)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Tests: SSE endpoint behavior (signal-based architecture)
#
# The SSE handler waits on in-memory signals fired by the Process Manager.
# These tests use _simulate_pm() to insert messages and fire signals in a
# background thread, simulating real PM behavior.
# ---------------------------------------------------------------------------


class TestDoneStream:
    def test_already_responded_returns_done(self, app, client, responded_conversation):
        """Completed conversations get an immediate done event."""
        response = client.get(
            f"/api/conversations/{responded_conversation.id}/stream",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        events = _parse_sse_events(response.content)
        assert len(events) == 1
        assert events[0]["event"] == "done"


class TestSSEFormat:
    def test_stream_ends_with_done(self, app, client, conversation):
        """SSE stream must end with a done event."""
        t = _simulate_pm(conversation.id, [("assistant", "Hello")])
        response = client.get(
            f"/api/conversations/{conversation.id}/stream",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        t.join()
        events = _parse_sse_events(response.content)
        assert events[-1]["event"] == "done"

    def test_assistant_event_has_content(self, app, client, conversation):
        """Assistant SSE events include the content field."""
        t = _simulate_pm(conversation.id, [("assistant", "My response")])
        response = client.get(
            f"/api/conversations/{conversation.id}/stream",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        t.join()
        events = _parse_sse_events(response.content)
        assistant = [e for e in events if e["event"] == "assistant"]
        assert len(assistant) == 1
        assert assistant[0]["data"]["content"] == "My response"

    def test_tool_events_in_sse(self, app, client, conversation):
        """Tool use and result events appear in SSE stream."""
        messages = [
            ("tool_use", json.dumps({"tool": "Read", "input": {"file_path": "x"}, "category": "read"})),
            ("tool_result", json.dumps({"output": "data"})),
            ("assistant", "Done"),
        ]
        t = _simulate_pm(conversation.id, messages)
        response = client.get(
            f"/api/conversations/{conversation.id}/stream",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        t.join()
        events = _parse_sse_events(response.content)
        types = [e["event"] for e in events]
        assert "tool_use" in types
        assert "tool_result" in types
        assert "assistant" in types


class TestRaceCondition:
    """PM writes messages before SSE handler connects."""

    def test_pm_writes_before_sse_connect(self, app, client):
        """Messages written by PM before SSE connect must still be streamed.

        Race condition: the PM can write messages between the client's POST
        (which enqueues the command) and the SSE connect.  The client passes
        ``after=<user_msg_id>`` so the SSE handler starts streaming from
        the user message onward — catching anything the PM wrote in between.
        """
        from web.signals import signals
        from web.storage import store

        conv = store.create_conversation(user_id="test@example.com")
        user_msg = store.add_message(conv.id, "user", "Hello")
        store.update_conversation(conv.id, needs_response=True)

        # PM writes a response BEFORE the SSE handler connects
        store.add_message(conv.id, "assistant", "Fast response")
        signals.notify_message(conv.id)

        # Then more messages arrive and PM finishes
        t = _simulate_pm(conv.id, [("assistant", "Second part")])
        response = client.get(
            f"/api/conversations/{conv.id}/stream?after={user_msg.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        t.join()
        events = _parse_sse_events(response.content)
        assistant = [e for e in events if e["event"] == "assistant"]

        assert len(assistant) >= 1, "No assistant events in SSE stream! Messages written before SSE connect were lost."
        # The first assistant message must be the one written before connect
        assert assistant[0]["data"]["content"] == "Fast response"

    def test_pm_finishes_before_sse_connect(self, app, client):
        """PM finishes entirely before SSE connect — messages must still arrive.

        If the PM is fast enough, needs_response is already False when the
        SSE handler connects.  The handler must still flush unseen messages
        before sending done.
        """
        from web.signals import signals
        from web.storage import store

        conv = store.create_conversation(user_id="test@example.com")
        user_msg = store.add_message(conv.id, "user", "Hello")
        store.update_conversation(conv.id, needs_response=True)

        # PM writes response AND finishes before SSE connects
        store.add_message(conv.id, "assistant", "Instant answer")
        signals.notify_message(conv.id)
        store.update_conversation(conv.id, needs_response=False)
        signals.notify_finished(conv.id)

        response = client.get(
            f"/api/conversations/{conv.id}/stream?after={user_msg.id}",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        events = _parse_sse_events(response.content)
        assistant = [e for e in events if e["event"] == "assistant"]

        assert len(assistant) == 1, "PM finished before SSE connect but assistant message was lost!"
        assert assistant[0]["data"]["content"] == "Instant answer"
        assert events[-1]["event"] == "done"


class TestNeedsResponse:
    """needs_response column controls stream behavior."""

    def test_needs_response_false_returns_done(self, app, client):
        """Conversation with needs_response=False returns immediate done."""
        from web.storage import store

        conv = store.create_conversation(user_id="test@example.com")
        store.add_message(conv.id, "user", "Hello")
        store.add_message(conv.id, "assistant", "Hi there")
        # needs_response defaults to False

        response = client.get(
            f"/api/conversations/{conv.id}/stream",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        events = _parse_sse_events(response.content)
        assert len(events) == 1
        assert events[0]["event"] == "done"

    def test_needs_response_true_streams_messages(self, app, client):
        """Conversation with needs_response=True streams PM messages."""
        from web.storage import store

        conv = store.create_conversation(user_id="test@example.com")
        store.add_message(conv.id, "user", "Hello")
        store.update_conversation(conv.id, needs_response=True)

        t = _simulate_pm(conv.id, [("assistant", "Response")])
        response = client.get(
            f"/api/conversations/{conv.id}/stream",
            headers={"X-Forwarded-Email": "test@example.com"},
        )
        t.join()
        events = _parse_sse_events(response.content)
        types = [e["event"] for e in events]
        assert "assistant" in types

    def test_update_conversation_clears_needs_response(self, app):
        """update_conversation(needs_response=False) works correctly."""
        from web.storage import store

        conv = store.create_conversation(user_id="test@example.com")
        store.add_message(conv.id, "user", "Hello")
        store.update_conversation(conv.id, needs_response=True)

        updated = store.get_conversation(conv.id)
        assert updated.needs_response is True

        store.update_conversation(conv.id, needs_response=False)
        updated = store.get_conversation(conv.id)
        assert updated.needs_response is False


# ---------------------------------------------------------------------------
# Tests: DB storage logic (tested directly, no SSE involved)
#
# These test the collect_events() storage invariants by simulating
# what happens in the streaming pipeline. Testing through SSE introduces
# non-deterministic async behavior.
# ---------------------------------------------------------------------------


class TestAppendMode:
    """append_mode affects how assistant chunks are joined in DB."""

    def test_ollama_append_concatenates_without_newline(self, app):
        """Ollama streaming: append=True → "".join (no newlines)."""
        from web.agents.base import AgentMessage
        from web.storage import store

        conv = store.create_conversation(user_id="test@example.com")
        store.add_message(conv.id, "user", "Hello")

        # Simulate collect_events() logic
        assistant_text_parts = []
        assistant_msg_id = None

        for event in [
            AgentMessage(type="assistant", content="Hello ", raw={"append": True}),
            AgentMessage(type="assistant", content="world!", raw={"append": True}),
        ]:
            assistant_text_parts.append(str(event.content))
            append_mode = bool(getattr(event, "raw", {}).get("append"))
            full_text = "".join(assistant_text_parts) if append_mode else "\n".join(assistant_text_parts)
            if assistant_msg_id is None:
                msg = store.add_message(conv.id, "assistant", full_text)
                assistant_msg_id = msg.id
            else:
                store.update_message(assistant_msg_id, full_text)

        # Verify
        conv = store.get_conversation(conv.id)
        assistant_msgs = [m for m in conv.messages if m.type == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].content == "Hello world!"

    def test_cli_joins_with_newlines(self, app):
        """CLI backend: no append flag → "\\n".join."""
        from web.agents.base import AgentMessage
        from web.storage import store

        conv = store.create_conversation(user_id="test@example.com")
        store.add_message(conv.id, "user", "Hello")

        assistant_text_parts = []
        assistant_msg_id = None

        for event in [
            AgentMessage(type="assistant", content="First paragraph"),
            AgentMessage(type="assistant", content="Second paragraph"),
        ]:
            assistant_text_parts.append(str(event.content))
            append_mode = bool(getattr(event, "raw", {}).get("append"))
            full_text = "".join(assistant_text_parts) if append_mode else "\n".join(assistant_text_parts)
            if assistant_msg_id is None:
                msg = store.add_message(conv.id, "assistant", full_text)
                assistant_msg_id = msg.id
            else:
                store.update_message(assistant_msg_id, full_text)

        conv = store.get_conversation(conv.id)
        assistant_msgs = [m for m in conv.messages if m.type == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].content == "First paragraph\nSecond paragraph"


class TestAssistantTextReset:
    """tool_use must reset assistant accumulation."""

    def test_tool_use_creates_separate_assistant_messages(self, app):
        """Text before and after a tool call are stored as separate DB messages."""
        from web.agents.base import AgentMessage
        from web.storage import store

        conv = store.create_conversation(user_id="test@example.com")
        store.add_message(conv.id, "user", "Hello")

        # Simulate collect_events() logic
        assistant_text_parts = []
        assistant_msg_id = None

        events = [
            AgentMessage(type="assistant", content="Let me check"),
            AgentMessage(type="tool_use", content={"tool": "Read", "input": {}}, raw={}),
            AgentMessage(type="tool_result", content={"output": "data"}, raw={}),
            AgentMessage(type="assistant", content="Here is what I found"),
        ]

        for event in events:
            if event.type == "assistant":
                assistant_text_parts.append(str(event.content))
                append_mode = bool(getattr(event, "raw", {}).get("append"))
                full_text = "".join(assistant_text_parts) if append_mode else "\n".join(assistant_text_parts)
                if assistant_msg_id is None:
                    msg = store.add_message(conv.id, "assistant", full_text)
                    assistant_msg_id = msg.id
                else:
                    store.update_message(assistant_msg_id, full_text)

            elif event.type in ("tool_use", "tool_result"):
                if event.type == "tool_use":
                    # Reset accumulation (matches conversations.py logic)
                    assistant_msg_id = None
                    assistant_text_parts = []
                store.add_message(conv.id, event.type, json.dumps(event.content))

        # Verify: two separate assistant messages
        conv = store.get_conversation(conv.id)
        assistant_msgs = [m for m in conv.messages if m.type == "assistant"]
        assert len(assistant_msgs) == 2
        assert assistant_msgs[0].content == "Let me check"
        assert assistant_msgs[1].content == "Here is what I found"


# ---------------------------------------------------------------------------
# Tests: Client disconnect must NOT kill the agent
#
# The SSE handler waits on signals — closing the connection just stops the
# generator. The PM continues running independently.
# ---------------------------------------------------------------------------


class TestClientDisconnect:
    """Client disconnect (page reload/navigation) must not kill the agent.

    When uvicorn detects TCP close, it calls aclose() on the
    StreamingResponse async generator. This just stops the signal
    listener — no agent task is affected.
    """

    def test_agent_survives_client_disconnect(self, app, conversation):
        """Agent must keep running after client disconnects mid-stream."""
        from web.routes.conversations import stream_conversation
        from web.storage import store

        # Insert a message so the SSE handler has something to stream
        store.add_message(conversation.id, "assistant", "Working on it...")

        async def _run():
            response = await stream_conversation(
                conv_id=conversation.id,
                after=0,
                user_email="test@example.com",
            )
            gen = response.body_iterator
            chunks_read = 0
            async for chunk in gen:
                chunks_read += 1
                if chunks_read >= 2:
                    break
            # Simulate client disconnect (uvicorn calls aclose on TCP close)
            await gen.aclose()
            await asyncio.sleep(0.1)

        asyncio.run(_run())

        # After disconnect: needs_response must still be True
        conv = store.get_conversation(conversation.id, include_messages=False)
        assert conv.needs_response, (
            "Agent was stopped by client disconnect! The SSE handler must not cancel the agent when client disconnects."
        )

        # No cancel command should have been enqueued
        pending = store.get_pending_pm_commands()
        cancel_cmds = [c for c in pending if c["conversation_id"] == conversation.id and c["command"] == "cancel"]
        assert not cancel_cmds, "Client disconnect enqueued a cancel command!"
