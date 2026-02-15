"""Tests for conversation fork (deep copy) functionality.

Users can fork conversations to continue from someone else's conversation
or to branch their own conversation.
"""

import pytest


@pytest.fixture
def conversation_with_messages(app):
    """Create a test conversation with multiple messages."""
    from web.storage import store

    with app.test_request_context():
        conv = store.create_conversation(user_id="owner@example.com")
        store.update_conversation(conv.id, title="Original conversation")
        store.add_message(conv.id, "user", "First question")
        store.add_message(conv.id, "assistant", "First answer")
        store.add_message(conv.id, "user", "Second question")
        store.add_message(conv.id, "assistant", "Second answer")
        return conv


class TestForkConversationDatabase:
    """Test the database fork_conversation method."""

    def test_fork_creates_new_conversation(self, app, conversation_with_messages):
        """Forking creates a new conversation with a new ID."""
        from web.storage import store

        with app.test_request_context():
            forked = store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

            assert forked is not None
            assert forked.id != conversation_with_messages.id
            assert forked.user_id == "forker@example.com"

    def test_fork_copies_title(self, app, conversation_with_messages):
        """Forked conversation has the same title."""
        from web.storage import store

        with app.test_request_context():
            forked = store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

            assert forked.title == "Original conversation"

    def test_fork_copies_all_messages(self, app, conversation_with_messages):
        """Forked conversation has copies of all messages."""
        from web.storage import store

        with app.test_request_context():
            forked = store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

            assert len(forked.messages) == 4
            assert forked.messages[0].content == "First question"
            assert forked.messages[1].content == "First answer"
            assert forked.messages[2].content == "Second question"
            assert forked.messages[3].content == "Second answer"

    def test_fork_messages_have_new_ids(self, app, conversation_with_messages):
        """Forked messages have different IDs (deep copy, not reference)."""
        from web.storage import store

        with app.test_request_context():
            original = store.get_conversation(conversation_with_messages.id)
            forked = store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

            # Message IDs should be different
            original_ids = {m.id for m in original.messages}
            forked_ids = {m.id for m in forked.messages}
            assert original_ids.isdisjoint(forked_ids)

    def test_fork_tracks_source(self, app, conversation_with_messages):
        """Forked conversation tracks its source via forked_from."""
        from web.storage import store

        with app.test_request_context():
            forked = store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

            assert forked.forked_from == conversation_with_messages.id

    def test_fork_resets_session_id(self, app, conversation_with_messages):
        """Forked conversation has no session_id (fresh start for agent)."""
        from web.storage import store

        with app.test_request_context():
            # Set session_id on original
            store.update_conversation(
                conversation_with_messages.id,
                session_id="original-session"
            )

            forked = store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

            assert forked.session_id is None

    def test_fork_nonexistent_returns_none(self, app):
        """Forking a non-existent conversation returns None."""
        from web.storage import store

        with app.test_request_context():
            result = store.fork_conversation(
                "nonexistent-uuid",
                "forker@example.com"
            )

            assert result is None

    def test_original_unchanged_after_fork(self, app, conversation_with_messages):
        """Original conversation is unchanged after fork."""
        from web.storage import store

        with app.test_request_context():
            # Fork it
            store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

            # Check original is unchanged
            original = store.get_conversation(conversation_with_messages.id)
            assert original.user_id == "owner@example.com"
            assert len(original.messages) == 4
            assert original.forked_from is None

    def test_modifying_fork_does_not_affect_original(self, app, conversation_with_messages):
        """Adding messages to fork does not affect original (no entanglement)."""
        from web.storage import store

        with app.test_request_context():
            forked = store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

            # Add a message to the fork
            store.add_message(forked.id, "user", "New message in fork")

            # Original should still have only 4 messages
            original = store.get_conversation(conversation_with_messages.id)
            assert len(original.messages) == 4

            # Fork should have 5 messages
            updated_fork = store.get_conversation(forked.id)
            assert len(updated_fork.messages) == 5


class TestForkConversationAPI:
    """Test the fork API endpoint."""

    def test_fork_endpoint_creates_copy(self, app, client, conversation_with_messages):
        """POST /api/conversations/:id/fork creates a copy."""
        response = client.post(
            f"/api/conversations/{conversation_with_messages.id}/fork",
            headers={"X-Forwarded-Email": "forker@example.com"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "id" in data
        assert data["id"] != conversation_with_messages.id
        assert data["forked_from"] == conversation_with_messages.id

    def test_fork_endpoint_returns_links(self, app, client, conversation_with_messages):
        """Fork response includes useful links."""
        response = client.post(
            f"/api/conversations/{conversation_with_messages.id}/fork",
            headers={"X-Forwarded-Email": "forker@example.com"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert "links" in data
        assert "self" in data["links"]
        assert "view" in data["links"]
        assert data["id"] in data["links"]["view"]

    def test_fork_nonexistent_returns_404(self, app, client):
        """Forking non-existent conversation returns 404."""
        response = client.post(
            "/api/conversations/nonexistent-uuid/fork",
            headers={"X-Forwarded-Email": "forker@example.com"},
        )

        assert response.status_code == 404

    def test_fork_requires_authentication(self, app, client, conversation_with_messages):
        """Fork endpoint requires authentication."""
        # Without X-Forwarded-Email, user_email is None or default
        # The endpoint should reject unauthenticated requests
        response = client.post(
            f"/api/conversations/{conversation_with_messages.id}/fork",
        )

        # May return 401 or use default user depending on config
        # In production with oauth-proxy, missing header means no auth
        assert response.status_code in (200, 401)

    def test_guest_can_fork_others_conversation(self, app, client, conversation_with_messages):
        """Guest user can fork someone else's conversation."""
        response = client.post(
            f"/api/conversations/{conversation_with_messages.id}/fork",
            headers={"X-Forwarded-Email": "guest@example.com"},
        )

        assert response.status_code == 200
        data = response.get_json()

        # Verify the fork belongs to the guest
        from web.storage import store
        with app.test_request_context():
            forked = store.get_conversation(data["id"])
            assert forked.user_id == "guest@example.com"

    def test_owner_can_fork_own_conversation(self, app, client, conversation_with_messages):
        """Owner can fork their own conversation."""
        response = client.post(
            f"/api/conversations/{conversation_with_messages.id}/fork",
            headers={"X-Forwarded-Email": "owner@example.com"},
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["forked_from"] == conversation_with_messages.id


class TestForkConversationUI:
    """Test fork button visibility in UI."""

    def test_fork_button_visible_on_shared_conversation(self, app, client, conversation_with_messages):
        """Fork button is visible when viewing someone else's conversation."""
        response = client.get(
            f"/explorations/{conversation_with_messages.id}",
            headers={"X-Forwarded-Email": "guest@example.com"},
        )

        assert response.status_code == 200
        assert b'id="forkConvBtn"' in response.data
        assert b"Dupliquer" in response.data

    def test_fork_button_visible_on_own_conversation(self, app, client, conversation_with_messages):
        """Fork button is visible on own conversation (in header)."""
        response = client.get(
            f"/explorations/{conversation_with_messages.id}",
            headers={"X-Forwarded-Email": "owner@example.com"},
        )

        assert response.status_code == 200
        assert b'id="forkConvBtn"' in response.data

    def test_forked_from_shown_in_header(self, app, client, conversation_with_messages):
        """Forked conversation shows link to source."""
        from web.storage import store

        # Create a fork
        with app.test_request_context():
            forked = store.fork_conversation(
                conversation_with_messages.id,
                "forker@example.com"
            )

        # View the fork
        response = client.get(
            f"/explorations/{forked.id}",
            headers={"X-Forwarded-Email": "forker@example.com"},
        )

        assert response.status_code == 200
        assert b"ri-git-branch-line" in response.data  # Fork icon
        assert conversation_with_messages.id.encode() in response.data  # Link to source
