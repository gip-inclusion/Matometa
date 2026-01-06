"""Agent backend implementations."""

from .base import AgentBackend, AgentMessage
from .cli import CLIBackend
from .sdk import SDKBackend

__all__ = ["AgentBackend", "AgentMessage", "CLIBackend", "SDKBackend", "get_agent"]


def get_agent() -> AgentBackend:
    """Get the configured agent backend."""
    from .. import config

    if config.AGENT_BACKEND == "sdk":
        return SDKBackend()
    else:
        return CLIBackend()
