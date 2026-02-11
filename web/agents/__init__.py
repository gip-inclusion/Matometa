"""Agent backend implementations."""

from .base import AgentBackend, AgentMessage
from .cli import CLIBackend
from .ollama import OllamaBackend
from .sdk import SDKBackend

__all__ = [
    "AgentBackend",
    "AgentMessage",
    "CLIBackend",
    "SDKBackend",
    "OllamaBackend",
    "get_agent",
]


def get_agent() -> AgentBackend:
    """Get the configured agent backend."""
    from .. import config

    backend = config.AGENT_BACKEND

    if backend == "ollama":
        return OllamaBackend()
    if backend == "sdk":
        return SDKBackend()
    if backend == "cli":
        return CLIBackend()

    raise ValueError(f"Unknown AGENT_BACKEND: {backend}")
