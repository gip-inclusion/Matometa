"""Tests for the cli-ollama backend."""

from unittest.mock import patch

import pytest


class TestCLIOllamaBackendEnv:
    def test_build_env_sets_ollama_vars(self):
        from web.agents.cli_ollama import CLIOllamaBackend

        backend = CLIOllamaBackend()
        env = backend._build_env("conv-123")

        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:11434"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "ollama"
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["MATOMETA_CONVERSATION_ID"] == "conv-123"

    def test_build_env_respects_custom_ollama_url(self):
        from web.agents.cli_ollama import CLIOllamaBackend

        with patch("web.agents.cli_ollama.config") as mock_config:
            mock_config.OLLAMA_BASE_URL = "http://gpu-server:11434"
            mock_config.OLLAMA_MODEL = "qwen3-coder"
            backend = CLIOllamaBackend()
            env = backend._build_env("conv-456")

        assert env["ANTHROPIC_BASE_URL"] == "http://gpu-server:11434"

    def test_extra_cmd_args_includes_model(self):
        from web.agents.cli_ollama import CLIOllamaBackend

        with patch("web.agents.cli_ollama.config") as mock_config:
            mock_config.OLLAMA_MODEL = "glm-4.7"
            backend = CLIOllamaBackend()
            args = backend._extra_cmd_args()

        assert args == ["--model", "glm-4.7"]


class TestCLIBackendHooks:
    """Verify the base CLIBackend hooks have the expected defaults."""

    def test_build_env_removes_api_key(self):
        from web.agents.cli import CLIBackend

        backend = CLIBackend()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-secret", "HOME": "/x"}, clear=True):
            env = backend._build_env("conv-1")

        assert "ANTHROPIC_API_KEY" not in env
        assert env["HOME"] == "/x"
        assert env["MATOMETA_CONVERSATION_ID"] == "conv-1"

    def test_extra_cmd_args_empty(self):
        from web.agents.cli import CLIBackend

        backend = CLIBackend()
        assert backend._extra_cmd_args() == []


class TestGetAgent:
    def test_get_agent_cli_ollama(self):
        from web.agents import get_agent
        from web.agents.cli_ollama import CLIOllamaBackend

        with patch("web.config.AGENT_BACKEND", "cli-ollama"):
            agent = get_agent()

        assert isinstance(agent, CLIOllamaBackend)

    def test_get_agent_cli_still_works(self):
        from web.agents import get_agent
        from web.agents.cli import CLIBackend

        with patch("web.config.AGENT_BACKEND", "cli"):
            agent = get_agent()

        assert isinstance(agent, CLIBackend)


class TestLLMRouting:
    def test_cli_ollama_routes_to_ollama_generate(self):
        with patch("web.llm._get_llm_backend", return_value="cli-ollama"), \
             patch("web.llm._ollama_generate", return_value="title") as mock_gen:
            from web.llm import generate_text
            result = generate_text("Generate a title")

        mock_gen.assert_called_once()
        assert result == "title"
