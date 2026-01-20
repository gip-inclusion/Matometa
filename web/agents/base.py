"""Abstract base class for agent backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional
import time


@dataclass
class AgentMessage:
    """Normalized message from agent backend (CLI or SDK)."""

    type: str  # "assistant", "tool_use", "tool_result", "system", "error"
    content: Any  # text, tool call details, etc.
    timestamp: float = field(default_factory=time.time)
    raw: dict = field(default_factory=dict)  # original message for debugging

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        result = {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        # Include raw data for system events (contains usage info)
        if self.type == "system" and self.raw:
            result["raw"] = self.raw
        return result


class AgentBackend(ABC):
    """Abstract interface for Claude agent backends."""

    @abstractmethod
    async def send_message(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentMessage]:
        """
        Send a message to the agent and yield streaming responses.

        Args:
            conversation_id: Unique ID for this conversation
            message: The user's message
            history: Previous messages in the conversation
            session_id: Optional session ID for agent resumption

        Yields:
            AgentMessage objects as they arrive
        """
        pass

    @abstractmethod
    async def cancel(self, conversation_id: str) -> bool:
        """
        Cancel a running conversation.

        Returns:
            True if cancelled, False if nothing was running
        """
        pass

    @abstractmethod
    def is_running(self, conversation_id: str) -> bool:
        """Check if a conversation is currently running."""
        pass
