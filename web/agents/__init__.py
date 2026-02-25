"""Agent backend implementations."""

from .base import AgentBackend, AgentMessage
from .cli import CLIBackend
from .cli_ollama import CLIOllamaBackend

__all__ = [
    "AgentBackend",
    "AgentMessage",
    "CLIBackend",
    "CLIOllamaBackend",
    "get_agent",
]


def get_agent() -> AgentBackend:
    """Get the configured agent backend."""
    from .. import config

    backend = config.AGENT_BACKEND

    if backend == "cli":
        return CLIBackend()
    if backend == "cli-ollama":
        return CLIOllamaBackend()

    raise ValueError(f"Unknown AGENT_BACKEND: {backend}")
