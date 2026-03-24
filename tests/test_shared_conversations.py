"""Tests for shared conversation access.

Users can share conversation links (containing UUIDs) with others.
When accessing a shared conversation:
- The conversation is viewable (read-only)
- The owner's email is shown in the header
- The chat input is disabled/hidden
- Users cannot send new messages to shared conversations
"""

import pytest


@pytest.fixture
def owner_client(app):
    from starlette.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def guest_client(app):
    from starlette.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def conversation(app, owner_client):
    from web.database import store

    # Create conversation as owner
    conv = store.create_conversation(user_id="owner@example.com")
    store.add_message(conv.id, "user", "Hello, this is a test message")
    store.add_message(conv.id, "assistant", "Hello! I'm here to help.")
    return conv


class TestSharedConversationAccess:
    """Test that users can view shared conversations."""

    def test_guest_can_view_shared_conversation(self, app, guest_client, conversation):
        """Guest can view a conversation owned by someone else."""
        response = guest_client.get(
            f"/explorations/{conversation.id}",
            headers={"X-Forwarded-Email": "guest@example.com"},
        )
        assert response.status_code == 200
        # Should show owner's email
        assert b"owner@example.com" in response.content
        assert b"Conversation de" in response.content

    def test_guest_sees_readonly_chat_bar(self, app, guest_client, conversation):
        """Guest sees read-only chat bar instead of input."""
        response = guest_client.get(
            f"/explorations/{conversation.id}",
            headers={"X-Forwarded-Email": "guest@example.com"},
        )
        assert response.status_code == 200
        assert b"Consultation seule" in response.content
        assert b'id="chatInput"' not in response.content

    def test_owner_sees_chat_input(self, app, owner_client, conversation):
        """Owner sees the chat input, not read-only bar."""
        response = owner_client.get(
            f"/explorations/{conversation.id}",
            headers={"X-Forwarded-Email": "owner@example.com"},
        )
        assert response.status_code == 200
        assert b"Consultation seule" not in response.content
        assert b'id="chatInput"' in response.content

    def test_nonexistent_conversation_redirects(self, app, guest_client):
        """Accessing a non-existent conversation redirects to list."""
        response = guest_client.get(
            "/explorations/nonexistent-uuid",
            headers={"X-Forwarded-Email": "guest@example.com"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/rechercher?show=convos"


class TestSharedConversationAPI:
    """Test API access to shared conversations."""

    def test_owner_can_get_conversation_api(self, app, owner_client, conversation):
        """Owner can GET their conversation via API."""
        response = owner_client.get(
            f"/api/conversations/{conversation.id}",
            headers={"X-Forwarded-Email": "owner@example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == conversation.id
        assert data["is_owner"] is True

    def test_guest_can_get_conversation_api(self, app, guest_client, conversation):
        """Guest can GET a shared conversation via API."""
        response = guest_client.get(
            f"/api/conversations/{conversation.id}",
            headers={"X-Forwarded-Email": "guest@example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == conversation.id
        assert data["is_owner"] is False

    def test_guest_cannot_send_message(self, app, guest_client, conversation):
        """Guest cannot send messages to a shared conversation."""
        response = guest_client.post(
            f"/api/conversations/{conversation.id}/messages",
            json={"content": "I want to add a message"},
            headers={
                "X-Forwarded-Email": "guest@example.com",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 403
        data = response.json()
        assert "appartient" in data["error"]  # French error message

    def test_owner_can_send_message(self, app, owner_client, conversation):
        """Owner can send messages to their conversation."""
        response = owner_client.post(
            f"/api/conversations/{conversation.id}/messages",
            json={"content": "Another message from owner"},
            headers={
                "X-Forwarded-Email": "owner@example.com",
                "Content-Type": "application/json",
            },
        )
        # Should succeed (or return 409 if already running, which is OK)
        assert response.status_code in (200, 409)

    def test_api_returns_messages_for_shared_conversation(self, app, guest_client, conversation):
        """API returns all messages for shared conversation."""
        response = guest_client.get(
            f"/api/conversations/{conversation.id}",
            headers={"X-Forwarded-Email": "guest@example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["content"] == "Hello, this is a test message"
        assert data["messages"][1]["content"] == "Hello! I'm here to help."


class TestRelaunchConversation:
    """Test admin relaunch of stuck shared conversations."""

    @pytest.fixture
    def stuck_conversation(self, app):
        from web.database import store

        conv = store.create_conversation(user_id="owner@example.com")
        store.add_message(conv.id, "user", "Hello")
        store.add_message(conv.id, "assistant", "Hi there!")
        store.add_message(conv.id, "user", "Do the thing please")
        return conv

    def test_admin_sees_relaunch_button(self, app, guest_client, stuck_conversation):
        """Admin viewing a stuck shared conversation sees the Relancer button."""
        response = guest_client.get(
            f"/explorations/{stuck_conversation.id}",
            headers={"X-Forwarded-Email": "admin@localhost"},
        )
        assert response.status_code == 200
        assert "Relancer" in response.text

    def test_non_admin_does_not_see_relaunch(self, app, guest_client, stuck_conversation):
        """Non-admin guest does not see the Relancer button."""
        response = guest_client.get(
            f"/explorations/{stuck_conversation.id}",
            headers={"X-Forwarded-Email": "guest@example.com"},
        )
        assert response.status_code == 200
        assert 'id="relaunchBtn"' not in response.text
        assert "Consultation seule" in response.text

    def test_owner_does_not_see_relaunch(self, app, owner_client, stuck_conversation):
        """Owner sees the normal chat input, not the relaunch button."""
        response = owner_client.get(
            f"/explorations/{stuck_conversation.id}",
            headers={"X-Forwarded-Email": "owner@example.com"},
        )
        assert response.status_code == 200
        assert 'id="relaunchBtn"' not in response.text
        assert b'id="chatInput"' in response.content

    def test_no_relaunch_when_last_message_is_assistant(self, app, guest_client, conversation):
        """No relaunch button when last message is from assistant (conversation completed)."""
        response = guest_client.get(
            f"/explorations/{conversation.id}",
            headers={"X-Forwarded-Email": "admin@localhost"},
        )
        assert response.status_code == 200
        assert 'id="relaunchBtn"' not in response.text

    def test_relaunch_api_works_for_admin(self, app, guest_client, stuck_conversation):
        """Admin can relaunch via API."""
        response = guest_client.post(
            f"/api/conversations/{stuck_conversation.id}/relaunch",
            headers={"X-Forwarded-Email": "admin@localhost"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "relaunched"

    def test_relaunch_api_denied_for_non_admin(self, app, guest_client, stuck_conversation):
        """Non-admin cannot relaunch via API."""
        response = guest_client.post(
            f"/api/conversations/{stuck_conversation.id}/relaunch",
            headers={"X-Forwarded-Email": "guest@example.com"},
        )
        assert response.status_code == 403

    def test_relaunch_api_denied_if_already_running(self, app, guest_client, stuck_conversation):
        """Cannot relaunch if conversation is already running."""
        from web.database import store

        store.update_conversation(stuck_conversation.id, needs_response=True)
        response = guest_client.post(
            f"/api/conversations/{stuck_conversation.id}/relaunch",
            headers={"X-Forwarded-Email": "admin@localhost"},
        )
        assert response.status_code == 409
