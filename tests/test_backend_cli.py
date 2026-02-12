"""Tests specific to the CLI backend."""

from unittest.mock import patch


class TestCLIBackendHooks:
    """Verify the base CLIBackend hook defaults."""

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
