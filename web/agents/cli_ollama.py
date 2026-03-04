"""CLI-Ollama backend — Claude Code CLI pointed at Ollama's Anthropic-compatible API."""

import os

from .. import config
from .cli import CLIBackend


class CLIOllamaBackend(CLIBackend):
    """CLIBackend that routes through Ollama instead of Anthropic."""

    def _build_env(self, conversation_id: str) -> dict:
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        # Translate our OLLAMA_* config into the ANTHROPIC_* env vars
        # that the Claude Code CLI expects for its API connection.
        env["ANTHROPIC_BASE_URL"] = config.OLLAMA_BASE_URL
        env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
        env["ANTHROPIC_API_KEY"] = ""
        env["MATOMETA_CONVERSATION_ID"] = conversation_id
        return env

    def _extra_cmd_args(self) -> list[str]:
        return ["--model", config.OLLAMA_MODEL]
