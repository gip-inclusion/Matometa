"""Tests specific to the CLI backend."""


def test_build_env_removes_api_key(mocker):
    from web.agents.cli import CLIBackend

    backend = CLIBackend()
    mocker.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-secret", "HOME": "/x"}, clear=True)
    env = backend._build_env()

    assert "ANTHROPIC_API_KEY" not in env
    assert env["HOME"] == "/x"


def test_extra_cmd_args_empty():
    from web.agents.cli import CLIBackend

    backend = CLIBackend()
    assert backend._extra_cmd_args() == []
