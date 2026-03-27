"""Generic backend tests — dispatch and LLM routing for all backends."""

import pytest


@pytest.mark.parametrize(
    "name,cls_name",
    [
        ("cli", "CLIBackend"),
        ("sdk", "SDKBackend"),
        ("cli-ollama", "CLIOllamaBackend"),
    ],
)
def test_get_agent_returns_correct_class(mocker, name, cls_name):
    from web.agents import get_agent

    mocker.patch("web.config.AGENT_BACKEND", name)
    agent = get_agent()
    assert type(agent).__name__ == cls_name


def test_get_agent_unknown_raises(mocker):
    from web.agents import get_agent

    mocker.patch("web.config.AGENT_BACKEND", "nope")
    with pytest.raises(ValueError, match="Unknown"):
        get_agent()


@pytest.mark.parametrize(
    "backend,expected_fn",
    [
        ("cli-ollama", "ollama_generate"),
        ("ollama", "ollama_generate"),
        ("cli", "claude_cli_generate"),
    ],
)
def test_llm_routes_to_correct_generator(mocker, backend, expected_fn):
    mocker.patch("web.llm.get_llm_backend", return_value=backend)
    mock_gen = mocker.patch(f"web.llm.{expected_fn}", return_value="ok")
    from web.llm import generate_text

    result = generate_text("test")

    mock_gen.assert_called_once()
    assert result == "ok"
