"""Tests for database module."""

import pytest

from web.database import (
    VALID_CONVERSATION_COLUMNS,
    VALID_REPORT_COLUMNS,
    _build_update_clause,
)
from web.storage import store


class TestBuildUpdateClause:
    """Tests for the SQL injection prevention helper."""

    def test_builds_valid_clause_single_column(self):
        """Single valid column produces correct clause."""
        clause, values = _build_update_clause({"title": "test"}, VALID_CONVERSATION_COLUMNS)
        assert clause == "title = %s"
        assert values == ["test"]

    def test_builds_valid_clause_multiple_columns(self):
        """Multiple valid columns produce correct clause."""
        clause, values = _build_update_clause({"title": "test", "status": "active"}, VALID_CONVERSATION_COLUMNS)
        assert "title = %s" in clause
        assert "status = %s" in clause
        assert len(values) == 2
        assert "test" in values
        assert "active" in values

    def test_rejects_invalid_column(self):
        """Invalid column raises ValueError."""
        with pytest.raises(ValueError, match="Invalid column name: malicious"):
            _build_update_clause({"malicious": "value"}, VALID_CONVERSATION_COLUMNS)

    def test_rejects_sql_injection_attempt(self):
        """SQL injection attempt in column name raises ValueError."""
        with pytest.raises(ValueError):
            _build_update_clause({"title; DROP TABLE users; --": "value"}, VALID_CONVERSATION_COLUMNS)

    def test_rejects_mixed_valid_invalid_columns(self):
        """Mix of valid and invalid columns raises ValueError."""
        with pytest.raises(ValueError, match="Invalid column name"):
            _build_update_clause({"title": "ok", "injected": "bad"}, VALID_CONVERSATION_COLUMNS)

    def test_conversation_columns_are_valid(self):
        """All conversation columns in the frozenset work."""
        for col in VALID_CONVERSATION_COLUMNS:
            clause, values = _build_update_clause({col: "test"}, VALID_CONVERSATION_COLUMNS)
            assert f"{col} = %s" in clause

    def test_report_columns_are_valid(self):
        """All report columns in the frozenset work."""
        for col in VALID_REPORT_COLUMNS:
            clause, values = _build_update_clause({col: "test"}, VALID_REPORT_COLUMNS)
            assert f"{col} = %s" in clause

    def test_empty_updates_produces_empty_clause(self):
        """Empty dict produces empty clause."""
        clause, values = _build_update_clause({}, VALID_CONVERSATION_COLUMNS)
        assert clause == ""
        assert values == []


class TestClearAllNeedsResponse:
    """Tests for the PM startup reconciliation method."""

    def test_clears_stuck_conversations(self, client):
        """Conversations with needs_response=True are cleared."""
        conv = store.create_conversation(user_id="test@test.com")
        store.update_conversation(conv.id, needs_response=True)

        cleared_ids = store.clear_all_needs_response()

        assert cleared_ids == [conv.id]
        updated = store.get_conversation(conv.id, include_messages=False)
        assert not updated.needs_response

    def test_noop_when_nothing_stuck(self, client):
        """Returns empty list when no conversations are stuck."""
        store.create_conversation(user_id="test@test.com")
        assert store.clear_all_needs_response() == []


class TestCancelUnstick:
    """Tests for the cancel endpoint force-clearing stuck conversations."""

    def test_cancel_unsticks_zombie_conversation(self, client):
        """Cancel clears needs_response when no pending run command exists."""
        conv = store.create_conversation(user_id="test@test.com")
        store.update_conversation(conv.id, needs_response=True)

        resp = client.post(f"/api/conversations/{conv.id}/cancel")

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        updated = store.get_conversation(conv.id, include_messages=False)
        assert not updated.needs_response

    def test_cancel_keeps_needs_response_when_pending(self, client):
        """Cancel does NOT clear needs_response when a run command is pending."""
        conv = store.create_conversation(user_id="test@test.com")
        store.update_conversation(conv.id, needs_response=True)
        store.enqueue_pm_command(conv.id, "run", {"prompt": "test"})

        resp = client.post(f"/api/conversations/{conv.id}/cancel")

        assert resp.status_code == 200
        updated = store.get_conversation(conv.id, include_messages=False)
        assert updated.needs_response
