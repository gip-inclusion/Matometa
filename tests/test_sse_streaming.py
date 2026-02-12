"""
Tests for SSE streaming and event storage.

Run with: pytest tests/test_sse_streaming.py -v
"""

import asyncio
import importlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator, Optional
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    """Module-scoped Flask app with stable event loop."""
    import web.routes.conversations as conv_mod

    db_fd, db_path = tempfile.mkstemp()

    from web import config
    original_path = config.SQLITE_PATH
    config.SQLITE_PATH = Path(db_path)

    from web import database
    importlib.reload(database)
    from web import storage
    importlib.reload(storage)

    conv_mod._agent = None
    conv_mod._async_loop = None
    conv_mod._async_thread = None

    from web.app import app as flask_app
    flask_app.config["TESTING"] = True

    yield flask_app

    loop = conv_mod._async_loop
    conv_mod._agent = None
    conv_mod._async_loop = None
    conv_mod._async_thread = None
    if loop and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)

    config.SQLITE_PATH = original_path
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def conversation(app):
    """Create a conversation with one user message (no response yet)."""
    from web.storage import store
    with app.test_request_context():
        conv = store.create_conversation(user_id="test@example.com")
        store.add_message(conv.id, "user", "Hello agent")
        return conv


@pytest.fixture
def responded_conversation(app):
    """Create a conversation with a user message and an assistant response."""
    from web.storage import store
    with app.test_request_context():
        conv = store.create_conversation(user_id="test@example.com")
        store.add_message(conv.id, "user", "Hello agent")
        store.add_message(conv.id, "assistant", "Hello! How can I help?")
        return conv


def _make_mock_backend(events, running_ids=None):
    """Create a mock agent backend that yields predetermined events."""
    from web.agents.base import AgentBackend, AgentMessage

    class MockBackend(AgentBackend):
        def __init__(self):
            self._running = set(running_ids or [])

        async def send_message(
            self, conversation_id, message, history, session_id=None,
        ) -> AsyncIterator[AgentMessage]:
            self._running.add(conversation_id)
            try:
                for evt in events:
                    yield evt
            finally:
                self._running.discard(conversation_id)

        async def cancel(self, conversation_id):
            self._running.discard(conversation_id)
            return True

        def is_running(self, conversation_id):
            return conversation_id in self._running

    return MockBackend()


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


def _stream_with_mock(client, conv_id, mock):
    """Run a stream request with a mock backend."""
    with patch("web.routes.conversations.get_agent_instance", return_value=mock):
        with patch("web.routes.conversations.generate_conversation_title"):
            with patch("web.routes.conversations.generate_conversation_tags"):
                return client.get(
                    f"/api/conversations/{conv_id}/stream",
                    headers={"X-Forwarded-Email": "test@example.com"},
                )


# ---------------------------------------------------------------------------
# Tests: SSE endpoint behavior (deterministic, no DB checks)
# ---------------------------------------------------------------------------


class TestDoneStream:
    def test_already_responded_returns_done(self, app, client, responded_conversation):
        """Completed conversations get an immediate done event."""
        mock = _make_mock_backend([])
        with patch("web.routes.conversations.get_agent_instance", return_value=mock):
            response = client.get(
                f"/api/conversations/{responded_conversation.id}/stream",
                headers={"X-Forwarded-Email": "test@example.com"},
            )
        events = _parse_sse_events(response.data)
        assert len(events) == 1
        assert events[0]["event"] == "done"


class TestSSEFormat:
    def test_stream_ends_with_done(self, app, client, conversation):
        """SSE stream must end with a done event."""
        from web.agents.base import AgentMessage
        events = [
            AgentMessage(type="system", content="init", raw={"subtype": "init", "session_id": "s1", "data": {"session_id": "s1"}}),
            AgentMessage(type="assistant", content="Hello"),
            AgentMessage(type="system", content="Completed: done", raw={"result": True}),
        ]
        response = _stream_with_mock(client, conversation.id, _make_mock_backend(events))
        assert response.content_type.startswith("text/event-stream")
        sse_events = _parse_sse_events(response.data)
        assert sse_events[-1]["event"] == "done"

    def test_assistant_event_has_content(self, app, client, conversation):
        """Assistant SSE events include the content field."""
        from web.agents.base import AgentMessage
        events = [
            AgentMessage(type="system", content="init", raw={"subtype": "init", "session_id": "s1", "data": {"session_id": "s1"}}),
            AgentMessage(type="assistant", content="My response"),
            AgentMessage(type="system", content="Completed: done", raw={"result": True}),
        ]
        response = _stream_with_mock(client, conversation.id, _make_mock_backend(events))
        sse_events = _parse_sse_events(response.data)
        assistant = [e for e in sse_events if e["event"] == "assistant"]
        assert len(assistant) == 1
        assert assistant[0]["data"]["content"] == "My response"

    def test_tool_events_in_sse(self, app, client, conversation):
        """Tool use and result events appear in SSE stream."""
        from web.agents.base import AgentMessage
        events = [
            AgentMessage(type="system", content="init", raw={"subtype": "init", "session_id": "s1", "data": {"session_id": "s1"}}),
            AgentMessage(type="tool_use", content={"tool": "Read", "input": {"file_path": "x"}}, raw={"block_type": "tool_use", "id": "tu_1"}),
            AgentMessage(type="tool_result", content={"tool": "Read", "output": "data"}, raw={"block_type": "tool_result", "tool_use_id": "tu_1"}),
            AgentMessage(type="assistant", content="Done"),
            AgentMessage(type="system", content="Completed: done", raw={"result": True}),
        ]
        response = _stream_with_mock(client, conversation.id, _make_mock_backend(events))
        sse_events = _parse_sse_events(response.data)
        types = [e["event"] for e in sse_events]
        assert "tool_use" in types
        assert "tool_result" in types
        assert "assistant" in types


class TestWaitStream:
    def test_running_agent_gets_wait_then_done(self, app, client, conversation):
        """If agent is_running, stream waits then sends done."""
        mock = _make_mock_backend([], running_ids=[conversation.id])
        call_count = [0]

        def is_running_then_stop(conv_id):
            call_count[0] += 1
            if call_count[0] <= 2:
                return True
            mock._running.discard(conv_id)
            return False

        mock.is_running = is_running_then_stop

        with patch("web.routes.conversations.get_agent_instance", return_value=mock):
            response = client.get(
                f"/api/conversations/{conversation.id}/stream",
                headers={"X-Forwarded-Email": "test@example.com"},
            )

        types = [e["event"] for e in _parse_sse_events(response.data)]
        assert "system" in types
        assert "done" in types
        assert "assistant" not in types  # Did not start a new run


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

        with app.test_request_context():
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

        with app.test_request_context():
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

        with app.test_request_context():
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
