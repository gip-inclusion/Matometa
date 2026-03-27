"""Agent backend implementations."""

from .. import config
from .base import AgentBackend, AgentMessage
from .cli import CLIBackend
from .cli_ollama import CLIOllamaBackend
from .sdk import SDKBackend

__all__ = [
    "AgentBackend",
    "AgentMessage",
    "get_agent",
]


def get_agent() -> AgentBackend:
    backend = config.AGENT_BACKEND

    if backend == "cli":
        return CLIBackend()
    if backend == "sdk":
        return SDKBackend()
    if backend == "cli-ollama":
        return CLIOllamaBackend()

    raise ValueError(f"Unknown AGENT_BACKEND: {backend}")
