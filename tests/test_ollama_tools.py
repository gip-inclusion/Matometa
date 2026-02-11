import importlib
import importlib.util
import re
import sys
import types

import pytest

# Import config and ollama_tools without pulling in the full web app.
# The web package eagerly imports Flask/SDK, which aren't available in CI.
# We register stub packages first, then load the specific modules by filepath.

_web_stub = types.ModuleType("web")
_web_stub.__path__ = ["web"]
_agents_stub = types.ModuleType("web.agents")
_agents_stub.__path__ = ["web/agents"]
sys.modules["web"] = _web_stub
sys.modules["web.agents"] = _agents_stub

# Load web.config directly from file
_spec = importlib.util.spec_from_file_location("web.config", "web/config.py")
config = importlib.util.module_from_spec(_spec)
sys.modules["web.config"] = config
_web_stub.config = config
_spec.loader.exec_module(config)

# Load web.agents.ollama_tools directly from file
_spec2 = importlib.util.spec_from_file_location("web.agents.ollama_tools", "web/agents/ollama_tools.py")
_tools_mod = importlib.util.module_from_spec(_spec2)
sys.modules["web.agents.ollama_tools"] = _tools_mod
_spec2.loader.exec_module(_tools_mod)

_bash_allowed = _tools_mod._bash_allowed
_edit_file = _tools_mod._edit_file
_grep_files = _tools_mod._grep_files
parse_tool_call = _tools_mod.parse_tool_call

# Load ollama.py helper functions (avoid httpx import issues by loading directly)
_spec3 = importlib.util.spec_from_file_location("web.agents.ollama", "web/agents/ollama.py")
_ollama_mod = importlib.util.module_from_spec(_spec3)
# Stub httpx and base module to avoid import errors
_httpx_stub = types.ModuleType("httpx")
_httpx_stub.AsyncClient = type("AsyncClient", (), {"__init__": lambda *a, **kw: None})
_httpx_stub.ConnectError = Exception
_httpx_stub.ReadTimeout = Exception
sys.modules.setdefault("httpx", _httpx_stub)
_base_stub = types.ModuleType("web.agents.base")
_base_stub.AgentBackend = type("AgentBackend", (), {})
_base_stub.AgentMessage = type("AgentMessage", (), {})
sys.modules["web.agents.base"] = _base_stub
_spec3.loader.exec_module(_ollama_mod)

_should_stream_text = _ollama_mod._should_stream_text


# ── parse_tool_call ──────────────────────────────────────────────

def test_parse_tool_call_json():
    payload = '{"tool": "Read", "input": {"file_path": "README.md"}}'
    parsed = parse_tool_call(payload)
    assert parsed == ("Read", {"file_path": "README.md"})


def test_parse_tool_call_code_fence():
    payload = '```json\n{"tool": "Glob", "input": {"pattern": "*.py"}}\n```'
    parsed = parse_tool_call(payload)
    assert parsed == ("Glob", {"pattern": "*.py"})


def test_parse_tool_call_returns_none_for_prose():
    assert parse_tool_call("Bonjour, je suis un assistant.") is None


def test_parse_tool_call_returns_none_for_missing_fields():
    assert parse_tool_call('{"tool": "Read"}') is None
    assert parse_tool_call('{"input": {"x": 1}}') is None


# ── _bash_allowed ────────────────────────────────────────────────

class TestBashAllowed:
    """Test _bash_allowed with realistic ALLOWED_TOOLS configs."""

    def test_bare_bash_allows_all(self, monkeypatch):
        monkeypatch.setattr(config, "ALLOWED_TOOLS", "Read,Write,Bash")
        assert _bash_allowed("rm -rf /") is True
        assert _bash_allowed("python3 script.py") is True

    def test_qualified_patterns_block_unmatched(self, monkeypatch):
        monkeypatch.setattr(
            config, "ALLOWED_TOOLS",
            "Read,Bash(python:*),Bash(curl:*inclusion.gouv.fr*)",
        )
        # python prefix matches
        assert _bash_allowed("python3 script.py") is True
        assert _bash_allowed("python run.py --flag") is True
        # curl to allowed domain matches
        assert _bash_allowed("curl https://inclusion.gouv.fr/api") is True
        # curl to other domain blocked
        assert _bash_allowed("curl https://evil.com") is False
        # unrecognized command blocked
        assert _bash_allowed("rm -rf /") is False
        assert _bash_allowed("wget https://inclusion.gouv.fr") is False

    def test_no_bash_blocks_all(self, monkeypatch):
        monkeypatch.setattr(config, "ALLOWED_TOOLS", "Read,Write,Glob")
        assert _bash_allowed("echo hello") is False

    def test_empty_allowed_tools_blocks_all(self, monkeypatch):
        monkeypatch.setattr(config, "ALLOWED_TOOLS", "")
        assert _bash_allowed("echo hello") is False

    def test_default_config_patterns(self, monkeypatch):
        """The default ALLOWED_TOOLS has Bash(python:*) etc but no bare Bash."""
        # Use the actual default from config
        monkeypatch.setattr(
            config, "ALLOWED_TOOLS",
            "Read,Write,Edit,Glob,Grep,"
            "Bash(curl:*inclusion.gouv.fr*),Bash(curl:*api.github.com*),"
            "Bash(jq:*),Bash(sqlite3:*),Bash(python:*),Bash(python3:*),"
            "Bash(.venv/bin/python:*)",
        )
        assert _bash_allowed("python3 query.py") is True
        assert _bash_allowed("jq '.data' file.json") is True
        assert _bash_allowed("sqlite3 db.sqlite 'SELECT 1'") is True
        assert _bash_allowed("curl https://api.github.com/repos") is True
        assert _bash_allowed("curl https://evil.com") is False
        assert _bash_allowed("rm -rf /") is False
        assert _bash_allowed("cat /etc/passwd") is False


# ── _edit_file ───────────────────────────────────────────────────

class TestEditFile:

    def test_find_and_replace(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\n")
        result = _edit_file({
            "file_path": str(f),
            "old_string": "hello",
            "new_string": "goodbye",
        })
        assert "Edited" in result
        assert f.read_text() == "goodbye world\n"

    def test_old_string_not_found(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\n")
        result = _edit_file({
            "file_path": str(f),
            "old_string": "missing",
            "new_string": "x",
        })
        assert "not found" in result
        assert f.read_text() == "hello world\n"  # unchanged

    def test_old_string_ambiguous(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("aaa\naaa\n")
        result = _edit_file({
            "file_path": str(f),
            "old_string": "aaa",
            "new_string": "bbb",
        })
        assert "matches 2 times" in result
        assert f.read_text() == "aaa\naaa\n"  # unchanged

    def test_missing_params(self):
        assert "Missing" in _edit_file({"file_path": "/tmp/x"})
        assert "Missing" in _edit_file({})


# ── _grep_files ──────────────────────────────────────────────────

class TestGrepFiles:

    def test_regex_search(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello_world():\n    pass\ndef goodbye():\n    pass\n")
        result = _grep_files({"pattern": r"def \w+_\w+", "path": str(f)})
        assert "hello_world" in result
        assert "goodbye" not in result  # no underscore

    def test_invalid_regex(self, tmp_path):
        result = _grep_files({"pattern": "[invalid", "path": str(tmp_path)})
        assert "Invalid regex" in result

    def test_path_defaults_to_cwd(self, tmp_path):
        # path defaults to "." which resolves to BASE_DIR
        f = tmp_path / "target.txt"
        f.write_text("findme_unique_token\n")
        result = _grep_files({"pattern": "findme_unique_token", "path": str(tmp_path)})
        assert "findme_unique_token" in result


# ── _should_stream_text ─────────────────────────────────────────

class TestShouldStreamText:

    def test_json_prefix_returns_false(self):
        assert _should_stream_text('{"tool": "Read"') is False

    def test_code_fence_returns_false(self):
        assert _should_stream_text("```json") is False

    def test_prose_returns_true(self):
        assert _should_stream_text("Bonjour, voici") is True

    def test_empty_returns_none(self):
        assert _should_stream_text("") is None

    def test_short_whitespace_returns_none(self):
        assert _should_stream_text("   ") is None

    def test_long_whitespace_caps_at_32(self):
        """Whitespace-only text longer than 32 chars should stop deferring."""
        assert _should_stream_text(" " * 33) is True

    def test_leading_whitespace_then_json(self):
        assert _should_stream_text("  {") is False

    def test_leading_whitespace_then_prose(self):
        assert _should_stream_text("  Hello") is True
