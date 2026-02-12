"""Tests specific to the cli-ollama backend."""

from unittest.mock import patch


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
