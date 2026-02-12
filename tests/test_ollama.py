"""
Tests for the Ollama backend: ollama.py, ollama_tools.py, llm.py.

Run with: pytest tests/test_ollama.py -v
"""

import asyncio
import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module loading: stub Flask/SDK so we can test in CI without them.
# ---------------------------------------------------------------------------

_web_stub = sys.modules.get("web") or types.ModuleType("web")
_web_stub.__path__ = ["web"]
_agents_stub = sys.modules.get("web.agents") or types.ModuleType("web.agents")
_agents_stub.__path__ = ["web/agents"]
sys.modules.setdefault("web", _web_stub)
sys.modules.setdefault("web.agents", _agents_stub)

if "web.config" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("web.config", "web/config.py")
    _config_mod = importlib.util.module_from_spec(_spec)
    sys.modules["web.config"] = _config_mod
    _web_stub.config = _config_mod
    _spec.loader.exec_module(_config_mod)
config = sys.modules["web.config"]

if "web.agents.ollama_tools" not in sys.modules:
    _spec2 = importlib.util.spec_from_file_location(
        "web.agents.ollama_tools", "web/agents/ollama_tools.py"
    )
    _tools_mod = importlib.util.module_from_spec(_spec2)
    sys.modules["web.agents.ollama_tools"] = _tools_mod
    _spec2.loader.exec_module(_tools_mod)
else:
    _tools_mod = sys.modules["web.agents.ollama_tools"]

_httpx_stub = sys.modules.get("httpx") or types.ModuleType("httpx")
_httpx_stub.AsyncClient = type(
    "AsyncClient",
    (),
    {"__init__": lambda *a, **kw: None, "is_closed": property(lambda s: False)},
)
_httpx_stub.ConnectError = type("ConnectError", (Exception,), {})
_httpx_stub.ReadTimeout = type("ReadTimeout", (Exception,), {})
_httpx_stub.Client = type("Client", (), {"__init__": lambda *a, **kw: None})
_httpx_stub.HTTPError = type("HTTPError", (Exception,), {})
sys.modules.setdefault("httpx", _httpx_stub)

_base_stub = sys.modules.get("web.agents.base")
if _base_stub is None:
    # Module not yet imported — create a minimal stub
    _base_stub = types.ModuleType("web.agents.base")
    _base_stub.AgentBackend = type("AgentBackend", (), {})
    _base_stub.AgentMessage = type(
        "AgentMessage",
        (),
        {
            "__init__": lambda self, **kw: self.__dict__.update(kw),
            "__repr__": lambda self: f"AgentMessage({self.__dict__})",
        },
    )
    sys.modules["web.agents.base"] = _base_stub

if "web.agents.ollama" not in sys.modules:
    _spec3 = importlib.util.spec_from_file_location(
        "web.agents.ollama", "web/agents/ollama.py"
    )
    _ollama_mod = importlib.util.module_from_spec(_spec3)
    sys.modules["web.agents.ollama"] = _ollama_mod
    _spec3.loader.exec_module(_ollama_mod)
else:
    _ollama_mod = sys.modules["web.agents.ollama"]

if "web.llm" not in sys.modules:
    _spec4 = importlib.util.spec_from_file_location("web.llm", "web/llm.py")
    _llm_mod = importlib.util.module_from_spec(_spec4)
    sys.modules["web.llm"] = _llm_mod
    _spec4.loader.exec_module(_llm_mod)
else:
    _llm_mod = sys.modules["web.llm"]

# Convenient references
_trim_history = _ollama_mod._trim_history
_should_stream_text = _ollama_mod._should_stream_text
_should_flush_buffer = _ollama_mod._should_flush_buffer
_looks_like_tool_start = _ollama_mod._looks_like_tool_start
_bash_allowed = _tools_mod._bash_allowed
_read_file = _tools_mod._read_file
_write_file = _tools_mod._write_file
_edit_file = _tools_mod._edit_file
_glob_files = _tools_mod._glob_files
_grep_files = _tools_mod._grep_files
_run_bash = _tools_mod._run_bash
_read_skill = _tools_mod._read_skill
_truncate = _tools_mod._truncate
_resolve_path = _tools_mod._resolve_path
_is_within = _tools_mod._is_within
parse_tool_call = _tools_mod.parse_tool_call
execute_tool = _tools_mod.execute_tool
tool_protocol = _tools_mod.tool_protocol
OllamaBackend = _ollama_mod.OllamaBackend


# ===================================================================
# parse_tool_call
# ===================================================================


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"tool": "Read", "input": {"file_path": "/tmp/x"}}', ("Read", {"file_path": "/tmp/x"})),
        ('```json\n{"tool": "Glob", "input": {"pattern": "*.py"}}\n```', ("Glob", {"pattern": "*.py"})),
        ('{"tool": "Read", "input": {"file_path": "/tmp/x"}, "reasoning": "ok"}', ("Read", {"file_path": "/tmp/x"})),
        # Prose + code fence (common Ollama pattern)
        ('Je vais lire le fichier.\n\n```json\n{"tool": "Read", "input": {"file_path": "/tmp/x"}}\n```', ("Read", {"file_path": "/tmp/x"})),
        # Prose + trailing JSON (no fence)
        ('Voici mon analyse.\n{"tool": "Bash", "input": {"command": "echo hi"}}', ("Bash", {"command": "echo hi"})),
        ("Hello, I'll help you with that.", None),
        ("", None),
        ("   ", None),
        ('{"input": {"x": 1}}', None),
        ('{"tool": "Read"}', None),
        ('{"tool": "Read", "input": "string"}', None),
        ("[1, 2, 3]", None),
    ],
    ids=[
        "valid_json",
        "code_fence",
        "extra_fields_ignored",
        "prose_then_code_fence",
        "prose_then_trailing_json",
        "prose",
        "empty",
        "whitespace",
        "missing_tool_key",
        "missing_input_key",
        "input_not_dict",
        "json_array",
    ],
)
def test_parse_tool_call(text, expected):
    assert parse_tool_call(text) == expected


# ===================================================================
# execute_tool dispatch
# ===================================================================


@pytest.mark.parametrize(
    "tool",
    ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"],
)
def test_execute_tool_missing_params(tool):
    result = execute_tool(tool, {})
    assert "Missing" in result


@pytest.mark.parametrize("bad_input", ["string", [1, 2], None])
def test_execute_tool_rejects_non_dict(bad_input):
    result = execute_tool("Read", bad_input)
    assert "Invalid tool input" in result


def test_execute_tool_unknown():
    assert "Unknown tool" in execute_tool("FakeWidget", {"x": 1})


# ===================================================================
# _bash_allowed
# ===================================================================


@pytest.mark.parametrize(
    "allowed_tools,command,expected",
    [
        # Bare Bash allows everything
        ("Bash", "rm -rf /", True),
        ("Bash,Bash(python:*)", "rm -rf /", True),
        # No Bash blocks everything
        ("Read,Write,Glob", "echo hello", False),
        ("", "echo hello", False),
        # Qualified patterns
        ("Bash(python:*)", "python script.py", True),
        ("Bash(python:*)", "python3 evil.py", False),  # prefix boundary
        ("Bash(python:)", "python", True),  # exact prefix, no args
        ("Bash(curl:*evil.com*)", "curly https://evil.com", False),  # prefix boundary
        # Semicolon injection
        ("Bash(python:*)", "python; rm -rf /", False),
        ("Bash(python:*)", "python ; rm -rf /", True),  # space is valid boundary
        # Multiple patterns
        ("Bash(python:*),Bash(jq:*)", "python script.py", True),
        ("Bash(python:*),Bash(jq:*)", "jq '.data' file.json", True),
        ("Bash(python:*),Bash(jq:*)", "curl evil.com", False),
        # Realistic default config
        (
            "Read,Bash(python:*),Bash(python3:*),Bash(curl:*inclusion.gouv.fr*)",
            "python3 script.py",
            True,
        ),
        (
            "Read,Bash(python:*),Bash(python3:*),Bash(curl:*inclusion.gouv.fr*)",
            "curl https://inclusion.gouv.fr/api",
            True,
        ),
        (
            "Read,Bash(python:*),Bash(python3:*),Bash(curl:*inclusion.gouv.fr*)",
            "curl https://evil.com",
            False,
        ),
        (
            "Read,Bash(python:*),Bash(python3:*),Bash(curl:*inclusion.gouv.fr*)",
            "wget https://inclusion.gouv.fr",
            False,
        ),
    ],
    ids=[
        "bare_bash_allows_all",
        "bare_bash_takes_precedence",
        "no_bash_blocks_all",
        "empty_config_blocks_all",
        "python_prefix_match",
        "python_prefix_boundary",
        "exact_prefix_no_args",
        "curl_prefix_boundary",
        "semicolon_not_word_boundary",
        "space_is_word_boundary",
        "multi_pattern_python",
        "multi_pattern_jq",
        "multi_pattern_unmatched",
        "default_python3",
        "default_curl_allowed_domain",
        "default_curl_blocked_domain",
        "default_wget_blocked",
    ],
)
def test_bash_allowed(monkeypatch, allowed_tools, command, expected):
    monkeypatch.setattr(config, "ALLOWED_TOOLS", allowed_tools)
    assert _bash_allowed(command) is expected


# ===================================================================
# _should_stream_text
# ===================================================================


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"tool": "Read"', False),
        ("```json", False),
        ("  {", False),
        ("Bonjour, voici", True),
        ("  Hello", True),
        (" " * 33, True),
        ("", None),
        ("   ", None),
    ],
    ids=[
        "json_prefix",
        "code_fence",
        "leading_ws_then_json",
        "prose",
        "leading_ws_then_prose",
        "long_whitespace_caps",
        "empty",
        "short_whitespace",
    ],
)
def test_should_stream_text(text, expected):
    assert _should_stream_text(text) is expected


# ===================================================================
# _should_flush_buffer
# ===================================================================


@pytest.mark.parametrize(
    "buffer,chunk_size,expected",
    [
        ("", 100, False),
        ("x" * 200, 200, True),
        ("x" * 50, 200, False),
        ("x", 0, True),
    ],
    ids=["empty_never", "at_size_flushes", "below_size_no_flush", "zero_size_always"],
)
def test_should_flush_buffer(buffer, chunk_size, expected):
    assert _should_flush_buffer(buffer, chunk_size) is expected


# ===================================================================
# _looks_like_tool_start
# ===================================================================


@pytest.mark.parametrize(
    "buffer,expected",
    [
        ("Je vais analyser le trafic", False),
        ("Bonjour\n\n```json\n{\"tool\":", True),
        ("Voici.\n```\n{\"tool\": \"Read\"}\n```", True),
        ('Voici.\n{"tool": "Read", "input": {}}', True),
        ('{"tool": "Read"}', False),  # no newline before { — this is the whole text
        ("", False),
    ],
    ids=[
        "pure_prose",
        "prose_then_code_fence",
        "code_fence_complete",
        "prose_then_raw_json",
        "bare_json_no_newline",
        "empty",
    ],
)
def test_looks_like_tool_start(buffer, expected):
    assert _looks_like_tool_start(buffer) is expected


# ===================================================================
# _truncate
# ===================================================================


def test_truncate_short_text():
    assert _truncate("hello") == "hello"


def test_truncate_exact_limit():
    text = "x" * _tools_mod.MAX_OUTPUT_CHARS
    assert _truncate(text) == text


def test_truncate_long_text():
    text = "x" * (_tools_mod.MAX_OUTPUT_CHARS + 5000)
    result = _truncate(text)
    assert len(result) < len(text)
    assert result.endswith("[truncated]")


# ===================================================================
# _resolve_path
# ===================================================================


def test_resolve_absolute_path():
    result = _resolve_path("/tmp/test.txt")
    assert result == Path("/tmp/test.txt").resolve()


def test_resolve_relative_to_base_dir():
    result = _resolve_path("README.md")
    assert result.is_absolute()
    assert str(result).endswith("README.md")


def test_resolve_tilde():
    result = _resolve_path("~/test.txt")
    assert "~" not in str(result)


# ===================================================================
# _is_within + symlinks
# ===================================================================


def test_is_within_basic():
    assert _is_within(Path("/tmp/x"), [Path("/tmp")]) is True


def test_is_within_outside():
    assert _is_within(Path("/etc/passwd"), [Path("/tmp"), Path("/home")]) is False


def test_is_within_root_itself():
    assert _is_within(Path("/tmp"), [Path("/tmp")]) is True


def test_symlink_escaping_root_blocked(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    link = allowed / "escape"
    link.symlink_to(secret)
    assert _is_within(link.resolve(), [allowed]) is False


def test_symlink_within_root_allowed(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "real.txt"
    target.write_text("ok")
    link = allowed / "alias"
    link.symlink_to(target)
    assert _is_within(link.resolve(), [allowed]) is True


def test_root_symlink_resolved_on_macos():
    import platform

    if platform.system() != "Darwin":
        pytest.skip("macOS-specific")
    resolved = Path("/tmp").resolve()
    assert _is_within(resolved / "test.txt", [Path("/tmp")]) is True


# ===================================================================
# File operations: _read_file
# ===================================================================


def test_read_within_base_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "readable.txt"
    f.write_text("content here")
    assert "content here" in _read_file({"file_path": str(f)})


def test_read_blocked_outside_roots(monkeypatch):
    monkeypatch.setattr(config, "ADDITIONAL_DIRS", [])
    result = _read_file({"file_path": "/etc/hostname"})
    assert "blocked" in result.lower()


def test_read_nonexistent():
    result = _read_file({"file_path": "/tmp/nonexistent_xyz_12345.txt"})
    assert "not found" in result.lower()


def test_read_binary_fallback(tmp_path, monkeypatch):
    """UnicodeDecodeError falls back to errors='replace'."""
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "binary.bin"
    f.write_bytes(b"hello\xff\xfeworld")
    result = _read_file({"file_path": str(f)})
    assert "hello" in result
    assert "world" in result


def test_read_large_file_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "large.txt"
    f.write_text("x" * (_tools_mod.MAX_OUTPUT_CHARS + 1000))
    result = _read_file({"file_path": str(f)})
    assert "[truncated]" in result


# ===================================================================
# File operations: _write_file
# ===================================================================


def test_write_blocked_outside_roots():
    result = _write_file({"file_path": "/etc/evil.txt", "content": "evil"})
    assert "blocked" in result.lower()


def test_write_missing_content():
    result = _write_file({"file_path": "/tmp/x"})
    assert "Missing" in result


def test_write_empty_content(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "empty.txt"
    result = _write_file({"file_path": str(f), "content": ""})
    assert "Wrote" in result
    assert f.exists()


def test_write_creates_parent_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    deep = tmp_path / "a" / "b" / "c" / "file.txt"
    result = _write_file({"file_path": str(deep), "content": "nested"})
    assert "Wrote" in result
    assert deep.read_text() == "nested"


# ===================================================================
# File operations: _edit_file
# ===================================================================


def test_edit_find_and_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world\n")
    result = _edit_file({"file_path": str(f), "old_string": "hello", "new_string": "goodbye"})
    assert "Edited" in result
    assert f.read_text() == "goodbye world\n"


def test_edit_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("hello world\n")
    result = _edit_file({"file_path": str(f), "old_string": "missing", "new_string": "x"})
    assert "not found" in result
    assert f.read_text() == "hello world\n"


def test_edit_ambiguous(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("aaa\naaa\n")
    result = _edit_file({"file_path": str(f), "old_string": "aaa", "new_string": "bbb"})
    assert "matches 2 times" in result
    assert f.read_text() == "aaa\naaa\n"


def test_edit_multiline(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3\n")
    result = _edit_file({"file_path": str(f), "old_string": "line1\nline2", "new_string": "replaced"})
    assert "Edited" in result
    assert f.read_text() == "replaced\nline3\n"


# ===================================================================
# _grep_files
# ===================================================================


def test_grep_regex(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "code.py"
    f.write_text("def hello_world():\n    pass\ndef goodbye():\n    pass\n")
    result = _grep_files({"pattern": r"def \w+_\w+", "path": str(f)})
    assert "hello_world" in result
    assert "goodbye" not in result


def test_grep_invalid_regex():
    result = _grep_files({"pattern": "[invalid", "path": "/tmp"})
    assert "Invalid regex" in result


def test_grep_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "empty.txt"
    f.write_text("")
    assert "No matches" in _grep_files({"pattern": "anything", "path": str(f)})


def test_grep_binary_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "binary.bin"
    f.write_bytes(b"\x00\x01\x02\xff\xfe")
    result = _grep_files({"pattern": ".*", "path": str(f)})
    assert isinstance(result, str)


def test_grep_result_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    f = tmp_path / "many.txt"
    f.write_text("\n".join(f"match_{i}" for i in range(300)))
    result = _grep_files({"pattern": "match_", "path": str(f)})
    assert len(result.strip().split("\n")) <= 200


# ===================================================================
# _glob_files
# ===================================================================


def test_glob_finds_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    (tmp_path / "foo.py").write_text("x")
    (tmp_path / "bar.py").write_text("y")
    result = _glob_files({"pattern": "*.py"})
    assert "foo.py" in result
    assert "bar.py" in result


def test_glob_no_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    assert "No matches" in _glob_files({"pattern": "*.xyz_nonexistent"})


def test_glob_recursive(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("x")
    assert "deep.py" in _glob_files({"pattern": "**/*.py"})


def test_glob_result_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    for i in range(250):
        (tmp_path / f"file_{i:03d}.txt").write_text("x")
    result = _glob_files({"pattern": "*.txt"})
    assert len(result.strip().split("\n")) <= 200


# ===================================================================
# _run_bash
# ===================================================================


def test_bash_blocked(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_TOOLS", "Bash(python:*)")
    assert "blocked" in _run_bash({"command": "rm -rf /"}).lower()


def test_bash_success(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_TOOLS", "Bash")
    assert "hello" in _run_bash({"command": "echo hello"})


def test_bash_no_output(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_TOOLS", "Bash")
    assert "(no output)" in _run_bash({"command": "true"})


def test_bash_captures_stderr(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_TOOLS", "Bash")
    result = _run_bash({"command": "echo oops >&2"})
    assert "oops" in result


def test_bash_output_truncated(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_TOOLS", "Bash")
    limit = _tools_mod.MAX_OUTPUT_CHARS
    result = _run_bash({"command": f"python3 -c \"print('x' * {limit + 5000})\""})
    assert "[truncated]" in result


def test_bash_timeout(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_BASH_TIMEOUT", 1)
    monkeypatch.setattr(config, "ALLOWED_TOOLS", "Bash")
    result = _run_bash({"command": "sleep 10"})
    assert "timed out" in result.lower()


# ===================================================================
# _read_skill
# ===================================================================


def test_skill_found_in_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    skill_dir = tmp_path / "skills" / "matomo_query"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Matomo Query")
    assert "Matomo Query" in _read_skill({"skill": "matomo_query"})


def test_skill_found_in_claude_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    skill_dir = tmp_path / ".claude" / "skills" / "my_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# My Skill")
    assert "My Skill" in _read_skill({"skill": "my_skill"})


def test_skill_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    assert "not found" in _read_skill({"skill": "nonexistent"}).lower()


# ===================================================================
# tool_protocol
# ===================================================================


def test_tool_protocol_lists_all_tools():
    proto = tool_protocol()
    for tool in ("Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"):
        assert tool in proto


# ===================================================================
# _trim_history
# ===================================================================


def test_trim_empty():
    assert _trim_history([], max_chars=1000) == []


def test_trim_all_fit():
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result = _trim_history(history, max_chars=1000)
    assert len(result) == 2
    assert result[0]["role"] == "user"


def test_trim_drops_oldest():
    history = [
        {"role": "user", "content": "a" * 100},
        {"role": "assistant", "content": "b" * 100},
        {"role": "user", "content": "c" * 100},
    ]
    result = _trim_history(history, max_chars=250)
    assert len(result) == 2
    assert result[0]["content"].startswith("b")
    assert result[1]["content"].startswith("c")


def test_trim_preserves_order():
    history = [
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
    ]
    result = _trim_history(history, max_chars=1000)
    assert [m["content"] for m in result] == ["1", "2", "3"]


def test_trim_strips_extra_fields():
    history = [{"role": "user", "content": "hi", "timestamp": 123, "metadata": {}}]
    result = _trim_history(history, max_chars=1000)
    assert set(result[0].keys()) == {"role", "content"}


def test_trim_zero_returns_empty():
    assert _trim_history([{"role": "user", "content": "hello"}], max_chars=0) == []


def test_trim_single_oversized_message_truncated():
    history = [{"role": "user", "content": "x" * 60000}]
    result = _trim_history(history, max_chars=50000)
    assert len(result) == 1
    assert len(result[0]["content"]) == 50000


def test_trim_oversized_drops_old_keeps_recent():
    history = [
        {"role": "user", "content": "old " * 10000},
        {"role": "assistant", "content": "recent " * 10000},
    ]
    result = _trim_history(history, max_chars=50000)
    assert len(result) >= 1
    assert result[-1]["role"] == "assistant"


# ===================================================================
# OllamaBackend: _build_options
# ===================================================================


def test_build_options_default(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_TEMPERATURE", 0.5)
    monkeypatch.setattr(config, "OLLAMA_NUM_CTX", 0)
    opts = OllamaBackend()._build_options()
    assert opts == {"temperature": 0.5}
    assert "num_ctx" not in opts


def test_build_options_with_num_ctx(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_TEMPERATURE", 0.2)
    monkeypatch.setattr(config, "OLLAMA_NUM_CTX", 8192)
    opts = OllamaBackend()._build_options()
    assert opts == {"temperature": 0.2, "num_ctx": 8192}


# ===================================================================
# OllamaBackend: _build_messages
# ===================================================================


def test_build_messages_structure(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "OLLAMA_MAX_HISTORY_CHARS", 50000)
    backend = OllamaBackend()
    history = [{"role": "user", "content": "prev"}]
    messages = backend._build_messages("hello", history)
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "hello"}
    assert len(messages) == 3  # system + 1 history + user


def test_build_messages_system_prompt_content(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    (tmp_path / "AGENTS.md").write_text("You are a helpful agent.")
    backend = OllamaBackend()
    messages = backend._build_messages("test", [])
    system = messages[0]["content"]
    assert "Aujourd'hui" in system
    assert "You are a helpful agent." in system
    assert "Outils disponibles" in system


# ===================================================================
# OllamaBackend: cancel / is_running
# ===================================================================


def test_is_running_false_for_unknown():
    assert OllamaBackend().is_running("nonexistent") is False


def test_cancel_returns_false_for_unknown():
    backend = OllamaBackend()
    assert asyncio.run(backend.cancel("nonexistent")) is False


# ===================================================================
# llm.py backend routing
# ===================================================================


class TestLLMBackendRouting:
    def test_unsupported_raises(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "nonexistent")
        monkeypatch.setattr(config, "AGENT_BACKEND", "nonexistent")
        with pytest.raises(_llm_mod.LLMError, match="Unsupported"):
            _llm_mod.generate_text("hello")

    def test_ollama_selected(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "ollama")
        assert _llm_mod._get_llm_backend() == "ollama"

    def test_llm_overrides_agent(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "sdk")
        monkeypatch.setattr(config, "AGENT_BACKEND", "ollama")
        assert _llm_mod._get_llm_backend() == "sdk"

    def test_defaults_to_agent(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_BACKEND", "")
        monkeypatch.setattr(config, "AGENT_BACKEND", "cli")
        assert _llm_mod._get_llm_backend() == "cli"


# ===================================================================
# Regression: llm.py timeout=0 preserved (was treated as falsy)
# ===================================================================


class TestOllamaGenerate:
    def test_basic_request_and_response(self, monkeypatch):
        monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://ollama:11434")
        captured = {}

        def fake_post(self, url, **kw):
            captured["url"] = url
            captured["payload"] = kw.get("json")
            resp = MagicMock()
            resp.json.return_value = {"response": "bonjour", "done": True}
            resp.raise_for_status = MagicMock()
            return resp

        FakeClient = type("Client", (), {
            "__init__": lambda self, **kw: None,
            "post": fake_post,
            "close": lambda self: None,
        })
        client = FakeClient()
        try:
            text = _llm_mod._ollama_generate(
                "Salut", model="qwen3-coder-next",
                max_tokens=5, temperature=0.1, timeout=10, client=client,
            )
        finally:
            client.close()

        assert text == "bonjour"
        assert captured["url"] == "http://ollama:11434/api/generate"
        assert captured["payload"]["model"] == "qwen3-coder-next"
        assert captured["payload"]["prompt"] == "Salut"


class TestOllamaGenerateTimeout:
    def _make_fake_client(self, captured):
        def fake_post(self_or_url, *a, **kw):
            resp = MagicMock()
            resp.json.return_value = {"response": "ok", "done": True}
            resp.raise_for_status = MagicMock()
            return resp

        def capture_init(self, *a, **kw):
            captured["timeout"] = kw.get("timeout")

        return type(
            "Client",
            (),
            {"__init__": capture_init, "post": fake_post, "close": lambda self: None},
        )

    def test_timeout_zero_preserved(self, monkeypatch):
        monkeypatch.setattr(config, "OLLAMA_REQUEST_TIMEOUT", 120)
        monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://fake:11434")
        captured = {}
        _httpx_stub.Client = self._make_fake_client(captured)
        try:
            _llm_mod._ollama_generate("test", model="t", max_tokens=10, temperature=0.2, timeout=0, client=None)
        finally:
            _httpx_stub.Client = type("Client", (), {"__init__": lambda *a, **kw: None})
        assert captured["timeout"] == 0

    def test_timeout_none_uses_default(self, monkeypatch):
        monkeypatch.setattr(config, "OLLAMA_REQUEST_TIMEOUT", 99)
        monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://fake:11434")
        captured = {}
        _httpx_stub.Client = self._make_fake_client(captured)
        try:
            _llm_mod._ollama_generate("test", model="t", max_tokens=10, temperature=0.2, timeout=None, client=None)
        finally:
            _httpx_stub.Client = type("Client", (), {"__init__": lambda *a, **kw: None})
        assert captured["timeout"] == 99


# ===================================================================
# Regression: OLLAMA_TOOL_MAX_STEPS capped at 20
# ===================================================================


def test_tool_max_steps_capped():
    assert config.OLLAMA_TOOL_MAX_STEPS <= 20
    assert config.OLLAMA_TOOL_MAX_STEPS >= 1
