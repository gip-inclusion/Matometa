from web.agents.ollama_tools import parse_tool_call


def test_parse_tool_call_json():
    payload = '{"tool": "Read", "input": {"file_path": "README.md"}}'
    parsed = parse_tool_call(payload)
    assert parsed == ("Read", {"file_path": "README.md"})
