"""Agent backend implementations."""

from .base import AgentBackend, AgentMessage

__all__ = [
    "AgentBackend",
    "AgentMessage",
    "get_agent",
]


def get_agent() -> AgentBackend:
    """Get the configured agent backend."""
    from .. import config

    backend = config.AGENT_BACKEND

    if backend == "cli":
        from .cli import CLIBackend

        return CLIBackend()
    if backend == "sdk":
        from .sdk import SDKBackend

        return SDKBackend()
    if backend == "cli-ollama":
        from .cli_ollama import CLIOllamaBackend

        return CLIOllamaBackend()

    raise ValueError(f"Unknown AGENT_BACKEND: {backend}")
