"""Conversation storage - in-memory for now, SQLite-ready structure."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class Message:
    """A single message in a conversation."""

    role: str  # "user" or "assistant"
    content: str  # text content
    timestamp: datetime = field(default_factory=datetime.now)
    raw_events: list[dict] = field(default_factory=list)  # full agent events
    # TODO: Add is_final_answer: bool field to distinguish intermediate assistant
    # messages from final answers. Needed for "minimal" view mode to work correctly
    # when loading old conversations. Currently all assistant text is joined into
    # one message, but streaming shows multiple blocks.


@dataclass
class Conversation:
    """A conversation with its messages and metadata."""

    id: str
    user_id: Optional[str]  # None for now, required when auth added
    title: Optional[str]  # auto-generated from first message
    messages: list[Message] = field(default_factory=list)
    session_id: Optional[str] = None  # agent session for resumption
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "session_id": self.session_id,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in self.messages
            ],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def get_history(self) -> list[dict]:
        """Get message history in format suitable for agent."""
        return [{"role": m.role, "content": m.content} for m in self.messages]


class ConversationStore:
    """
    In-memory conversation store.

    Swap to SQLite later by reimplementing these methods.
    """

    def __init__(self):
        self._conversations: dict[str, Conversation] = {}

    def create(self, user_id: Optional[str] = None) -> Conversation:
        """Create a new conversation."""
        conv = Conversation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=None,
        )
        self._conversations[conv.id] = conv
        return conv

    def get(self, conv_id: str) -> Optional[Conversation]:
        """Get a conversation by ID."""
        return self._conversations.get(conv_id)

    def append_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        raw_events: Optional[list[dict]] = None,
    ) -> Optional[Message]:
        """Append a message to a conversation."""
        conv = self._conversations.get(conv_id)
        if not conv:
            return None

        msg = Message(
            role=role,
            content=content,
            raw_events=raw_events or [],
        )
        conv.messages.append(msg)
        conv.updated_at = datetime.now()

        # Auto-generate title from first user message
        if conv.title is None and role == "user":
            conv.title = content[:50] + ("..." if len(content) > 50 else "")

        return msg

    def update_session_id(self, conv_id: str, session_id: str) -> bool:
        """Update the agent session ID for a conversation."""
        conv = self._conversations.get(conv_id)
        if not conv:
            return False
        conv.session_id = session_id
        return True

    def update_title(self, conv_id: str, title: str) -> bool:
        """Update the title for a conversation."""
        conv = self._conversations.get(conv_id)
        if not conv:
            return False
        conv.title = title
        return True

    def list_recent(
        self, user_id: Optional[str] = None, limit: int = 20
    ) -> list[Conversation]:
        """
        List recent conversations.

        Args:
            user_id: Filter by user (None = all users, for now)
            limit: Maximum number to return
        """
        convs = list(self._conversations.values())

        if user_id is not None:
            convs = [c for c in convs if c.user_id == user_id]

        # Sort by updated_at descending
        convs.sort(key=lambda c: c.updated_at, reverse=True)

        return convs[:limit]

    def delete(self, conv_id: str) -> bool:
        """Delete a conversation."""
        if conv_id in self._conversations:
            del self._conversations[conv_id]
            return True
        return False


# Global store instance - use SQLite for persistence
from .database import SQLiteConversationStore
store = SQLiteConversationStore()
