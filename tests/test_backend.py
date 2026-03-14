"""Generic backend tests — dispatch and LLM routing for all backends."""

from unittest.mock import patch

import pytest


class TestGetAgent:
    """Every registered backend must return the right class."""

    @pytest.mark.parametrize(
        "name,cls_name",
        [
            ("cli", "CLIBackend"),
            ("sdk", "SDKBackend"),
            ("cli-ollama", "CLIOllamaBackend"),
        ],
    )
    def test_get_agent_returns_correct_class(self, name, cls_name):
        from web.agents import get_agent

        with patch("web.config.AGENT_BACKEND", name):
            agent = get_agent()

        assert type(agent).__name__ == cls_name

    def test_get_agent_unknown_raises(self):
        from web.agents import get_agent

        with patch("web.config.AGENT_BACKEND", "nope"):
            with pytest.raises(ValueError, match="Unknown"):
                get_agent()


class TestLLMRouting:
    """LLM short-prompt routing for every backend."""

    @pytest.mark.parametrize(
        "backend,expected_fn",
        [
            ("cli-ollama", "_ollama_generate"),
            ("ollama", "_ollama_generate"),
            ("cli", "_claude_cli_generate"),
        ],
    )
    def test_routes_to_correct_generator(self, backend, expected_fn):
        with (
            patch("web.llm._get_llm_backend", return_value=backend),
            patch(f"web.llm.{expected_fn}", return_value="ok") as mock_gen,
        ):
            from web.llm import generate_text

            result = generate_text("test")

        mock_gen.assert_called_once()
        assert result == "ok"
