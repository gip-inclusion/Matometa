"""Tests for usage tracking across backends."""

import pytest


class TestConversationUsageFields:
    """Tests for usage fields on Conversation dataclass."""

    def test_conversation_has_usage_input_tokens_field(self):
        """Conversation dataclass has usage_input_tokens field defaulting to 0."""
        from web.database import Conversation

        conv = Conversation()
        assert hasattr(conv, "usage_input_tokens")
        assert conv.usage_input_tokens == 0

    def test_conversation_has_usage_output_tokens_field(self):
        """Conversation dataclass has usage_output_tokens field defaulting to 0."""
        from web.database import Conversation

        conv = Conversation()
        assert hasattr(conv, "usage_output_tokens")
        assert conv.usage_output_tokens == 0

    def test_conversation_has_usage_cache_creation_tokens_field(self):
        """Conversation dataclass has usage_cache_creation_tokens field defaulting to 0."""
        from web.database import Conversation

        conv = Conversation()
        assert hasattr(conv, "usage_cache_creation_tokens")
        assert conv.usage_cache_creation_tokens == 0

    def test_conversation_has_usage_cache_read_tokens_field(self):
        """Conversation dataclass has usage_cache_read_tokens field defaulting to 0."""
        from web.database import Conversation

        conv = Conversation()
        assert hasattr(conv, "usage_cache_read_tokens")
        assert conv.usage_cache_read_tokens == 0

    def test_conversation_has_usage_backend_field(self):
        """Conversation dataclass has usage_backend field defaulting to None."""
        from web.database import Conversation

        conv = Conversation()
        assert hasattr(conv, "usage_backend")
        assert conv.usage_backend is None

    def test_conversation_has_usage_extra_field(self):
        """Conversation dataclass has usage_extra field defaulting to None."""
        from web.database import Conversation

        conv = Conversation()
        assert hasattr(conv, "usage_extra")
        assert conv.usage_extra is None

    def test_conversation_to_dict_includes_usage_fields(self):
        """Conversation.to_dict() includes all usage fields."""
        from web.database import Conversation

        conv = Conversation(
            usage_input_tokens=100,
            usage_output_tokens=50,
            usage_cache_creation_tokens=20,
            usage_cache_read_tokens=80,
            usage_backend="cli",
            usage_extra={"service_tier": "standard"},
        )
        data = conv.to_dict()
        assert data["usage_input_tokens"] == 100
        assert data["usage_output_tokens"] == 50
        assert data["usage_cache_creation_tokens"] == 20
        assert data["usage_cache_read_tokens"] == 80
        assert data["usage_backend"] == "cli"
        assert data["usage_extra"] == {"service_tier": "standard"}


class TestDatabaseUsageColumns:
    """Tests for usage columns in database schema."""

    @pytest.fixture(autouse=True)
    def db_setup(self):
        from web.database import init_db

        init_db()
        yield
        from web.db import get_db

        with get_db() as conn:
            conn.execute_raw("""
                TRUNCATE TABLE messages, conversation_tags, report_tags,
                    uploaded_files, cron_runs, pinned_items, pm_commands,
                    pm_heartbeat, reports, conversations, tags, schema_version
                    CASCADE;
            """)

    def test_conversations_table_has_usage_columns(self):
        """Conversations table has all usage columns."""
        from web.database import get_db

        with get_db() as conn:
            cursor = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s", ("conversations",)
            )
            columns = {row["column_name"] for row in cursor.fetchall()}
            assert "usage_input_tokens" in columns
            assert "usage_output_tokens" in columns
            assert "usage_cache_creation_tokens" in columns
            assert "usage_cache_read_tokens" in columns
            assert "usage_backend" in columns
            assert "usage_extra" in columns

    def test_create_conversation_stores_zero_usage(self):
        """New conversations start with zero usage."""
        from web.database import ConversationStore

        store = ConversationStore()
        conv = store.create_conversation(user_id="test")

        loaded = store.get_conversation(conv.id)
        assert loaded.usage_input_tokens == 0
        assert loaded.usage_output_tokens == 0
        assert loaded.usage_cache_creation_tokens == 0
        assert loaded.usage_cache_read_tokens == 0
        assert loaded.usage_backend is None
        assert loaded.usage_extra is None

    def test_update_conversation_usage(self):
        """Can update usage on a conversation."""
        from web.database import ConversationStore

        store = ConversationStore()
        conv = store.create_conversation(user_id="test")

        # Update usage
        store.update_conversation_usage(
            conv.id,
            input_tokens=1500,
            output_tokens=800,
            cache_creation_tokens=100,
            cache_read_tokens=500,
            backend="sdk",
            extra={"service_tier": "priority", "web_search_requests": 2},
        )

        loaded = store.get_conversation(conv.id)
        assert loaded.usage_input_tokens == 1500
        assert loaded.usage_output_tokens == 800
        assert loaded.usage_cache_creation_tokens == 100
        assert loaded.usage_cache_read_tokens == 500
        assert loaded.usage_backend == "sdk"
        assert loaded.usage_extra == {"service_tier": "priority", "web_search_requests": 2}

    def test_accumulate_usage(self):
        """Can accumulate usage incrementally."""
        from web.database import ConversationStore

        store = ConversationStore()
        conv = store.create_conversation(user_id="test")

        # First exchange
        store.accumulate_usage(
            conv.id,
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=10,
            cache_read_tokens=0,
            backend="cli",
        )
        loaded = store.get_conversation(conv.id)
        assert loaded.usage_input_tokens == 100
        assert loaded.usage_output_tokens == 50
        assert loaded.usage_cache_creation_tokens == 10
        assert loaded.usage_cache_read_tokens == 0
        assert loaded.usage_backend == "cli"

        # Second exchange
        store.accumulate_usage(
            conv.id,
            input_tokens=200,
            output_tokens=150,
            cache_creation_tokens=0,
            cache_read_tokens=80,
        )
        loaded = store.get_conversation(conv.id)
        assert loaded.usage_input_tokens == 300
        assert loaded.usage_output_tokens == 200
        assert loaded.usage_cache_creation_tokens == 10
        assert loaded.usage_cache_read_tokens == 80
        # Backend should persist from first call
        assert loaded.usage_backend == "cli"


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
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 400,
                }
            },
        )
        assert msg.raw["usage"]["input_tokens"] == 1000
        assert msg.raw["usage"]["output_tokens"] == 500
        assert msg.raw["usage"]["cache_creation_input_tokens"] == 100
        assert msg.raw["usage"]["cache_read_input_tokens"] == 400


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
            },
        }

        msgs = backend._parse_events(event)
        assert len(msgs) == 1
        assert msgs[0].raw.get("usage") == {"input_tokens": 1234, "output_tokens": 567}

    def test_parse_result_event_without_usage(self):
        """CLI backend handles result event without usage gracefully."""
        from web.agents.cli import CLIBackend

        backend = CLIBackend()

        event = {
            "type": "result",
            "subtype": "success",
        }

        msgs = backend._parse_events(event)
        assert len(msgs) == 1
        # Should not error, usage may be absent
