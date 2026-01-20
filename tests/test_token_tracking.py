"""Tests for token tracking across backends."""

import pytest
import tempfile
import os
from pathlib import Path


class TestConversationTokenFields:
    """Tests for token fields on Conversation dataclass."""

    def test_conversation_has_input_tokens_field(self):
        """Conversation dataclass has input_tokens field defaulting to 0."""
        from web.database import Conversation

        conv = Conversation()
        assert hasattr(conv, 'input_tokens')
        assert conv.input_tokens == 0

    def test_conversation_has_output_tokens_field(self):
        """Conversation dataclass has output_tokens field defaulting to 0."""
        from web.database import Conversation

        conv = Conversation()
        assert hasattr(conv, 'output_tokens')
        assert conv.output_tokens == 0

    def test_conversation_to_dict_includes_tokens(self):
        """Conversation.to_dict() includes token fields."""
        from web.database import Conversation

        conv = Conversation(input_tokens=100, output_tokens=50)
        data = conv.to_dict()
        assert data['input_tokens'] == 100
        assert data['output_tokens'] == 50


class TestDatabaseTokenColumns:
    """Tests for token columns in database schema."""

    @pytest.fixture
    def temp_db(self, tmp_path, monkeypatch):
        """Create a temporary database for testing."""
        db_path = tmp_path / "test.db"
        monkeypatch.setattr('web.database.DB_PATH', db_path)
        # Re-import to use patched path
        import importlib
        import web.database
        importlib.reload(web.database)
        return db_path

    def test_conversations_table_has_input_tokens_column(self, temp_db):
        """Conversations table has input_tokens column."""
        from web.database import init_db, get_db

        init_db()

        with get_db() as conn:
            cursor = conn.execute("PRAGMA table_info(conversations)")
            columns = {row['name'] for row in cursor.fetchall()}
            assert 'input_tokens' in columns

    def test_conversations_table_has_output_tokens_column(self, temp_db):
        """Conversations table has output_tokens column."""
        from web.database import init_db, get_db

        init_db()

        with get_db() as conn:
            cursor = conn.execute("PRAGMA table_info(conversations)")
            columns = {row['name'] for row in cursor.fetchall()}
            assert 'output_tokens' in columns

    def test_create_conversation_stores_zero_tokens(self, temp_db):
        """New conversations start with zero tokens."""
        from web.database import ConversationStore

        store = ConversationStore()
        conv = store.create_conversation(user_id="test")

        loaded = store.get_conversation(conv.id)
        assert loaded.input_tokens == 0
        assert loaded.output_tokens == 0

    def test_update_conversation_tokens(self, temp_db):
        """Can update token counts on a conversation."""
        from web.database import ConversationStore

        store = ConversationStore()
        conv = store.create_conversation(user_id="test")

        # Update tokens
        store.update_conversation_tokens(conv.id, input_tokens=1500, output_tokens=800)

        loaded = store.get_conversation(conv.id)
        assert loaded.input_tokens == 1500
        assert loaded.output_tokens == 800

    def test_accumulate_tokens(self, temp_db):
        """Can accumulate tokens incrementally."""
        from web.database import ConversationStore

        store = ConversationStore()
        conv = store.create_conversation(user_id="test")

        # First exchange
        store.accumulate_tokens(conv.id, input_tokens=100, output_tokens=50)
        loaded = store.get_conversation(conv.id)
        assert loaded.input_tokens == 100
        assert loaded.output_tokens == 50

        # Second exchange
        store.accumulate_tokens(conv.id, input_tokens=200, output_tokens=150)
        loaded = store.get_conversation(conv.id)
        assert loaded.input_tokens == 300
        assert loaded.output_tokens == 200


class TestAgentMessageTokens:
    """Tests for token information in AgentMessage."""

    def test_agent_message_can_carry_usage(self):
        """AgentMessage can carry token usage in raw dict."""
        from web.agents.base import AgentMessage

        msg = AgentMessage(
            type="system",
            content="done",
            raw={
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                }
            }
        )
        assert msg.raw['usage']['input_tokens'] == 1000
        assert msg.raw['usage']['output_tokens'] == 500


class TestCLIBackendTokenExtraction:
    """Tests for token extraction from CLI backend."""

    def test_parse_result_event_extracts_tokens(self):
        """CLI backend extracts tokens from result event."""
        from web.agents.cli import CLIBackend

        backend = CLIBackend()

        # Simulate a result event with usage info
        event = {
            "type": "result",
            "subtype": "success",
            "usage": {
                "input_tokens": 1234,
                "output_tokens": 567,
            }
        }

        msg = backend._parse_event(event)
        assert msg is not None
        assert msg.raw.get('usage') == {"input_tokens": 1234, "output_tokens": 567}

    def test_parse_result_event_without_usage(self):
        """CLI backend handles result event without usage gracefully."""
        from web.agents.cli import CLIBackend

        backend = CLIBackend()

        event = {
            "type": "result",
            "subtype": "success",
        }

        msg = backend._parse_event(event)
        assert msg is not None
        # Should not error, usage may be absent


class TestSDKBackendTokenExtraction:
    """Tests for token extraction from SDK backend."""

    def test_normalize_result_message_extracts_tokens(self):
        """SDK backend extracts tokens from ResultMessage."""
        from web.agents.sdk import SDKBackend
        from unittest.mock import MagicMock

        backend = SDKBackend()

        # Create a mock ResultMessage with usage attribute
        mock_result = MagicMock()
        mock_result.__class__.__name__ = 'ResultMessage'
        mock_result.subtype = 'success'
        mock_result.usage = MagicMock()
        mock_result.usage.input_tokens = 2000
        mock_result.usage.output_tokens = 1000

        # Need to make isinstance check work
        from claude_agent_sdk import ResultMessage
        mock_result.__class__ = ResultMessage

        messages = backend._normalize_message(mock_result)
        assert len(messages) >= 1

        # Find the system message
        system_msg = next((m for m in messages if m.type == "system"), None)
        assert system_msg is not None
        assert system_msg.raw.get('usage') == {"input_tokens": 2000, "output_tokens": 1000}
