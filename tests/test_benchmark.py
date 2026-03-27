"""Tests for web/benchmark.py — unit tests with mocked externals."""

import json
from datetime import datetime, timedelta

import pytest

from web.benchmark import (
    PromptResult,
    _history_for_prompt,
    _original_metrics,
    _run_prompt_line,
    _table_row,
    _yield_summary_table,
)
from web.database import Conversation, Message


def _msg(type: str, content: str, ts: datetime, id: int = 0) -> Message:
    return Message(id=id, conversation_id="c1", type=type, content=content, created_at=ts)


def _tool_use_content(tool: str, category: str) -> str:
    return json.dumps({"tool": tool, "input": {}, "category": category})


T0 = datetime(2026, 3, 1, 10, 0, 0)


@pytest.fixture
def two_prompt_conv():
    msgs = [
        _msg("user", "Quel est le trafic ?", T0, id=1),
        _msg("tool_use", _tool_use_content("Bash", "API: Matomo"), T0 + timedelta(seconds=10), id=2),
        _msg("tool_result", "result data", T0 + timedelta(seconds=15), id=3),
        _msg("assistant", "Voici le trafic.", T0 + timedelta(seconds=30), id=4),
        _msg("user", "Compare avec février", T0 + timedelta(seconds=60), id=5),
        _msg("tool_use", _tool_use_content("Bash", "API: Matomo"), T0 + timedelta(seconds=70), id=6),
        _msg("tool_use", _tool_use_content("Read", "Read: knowledge"), T0 + timedelta(seconds=75), id=7),
        _msg("assistant", "Voici la comparaison.", T0 + timedelta(seconds=120), id=8),
    ]
    return Conversation(
        id="c1",
        title="Trafic mars",
        messages=msgs,
        usage_input_tokens=40000,
        usage_output_tokens=10000,
    )


class TestOriginalMetrics:
    def test_prompt_count_and_durations(self, two_prompt_conv):
        m = _original_metrics(two_prompt_conv)
        assert m["prompt_count"] == 2
        assert m["prompt_durations"][0] == 60.0
        assert m["prompt_durations"][1] == 60.0
        assert m["total_s"] == 120.0

    def test_tool_counting(self, two_prompt_conv):
        m = _original_metrics(two_prompt_conv)
        assert m["tools"]["Bash"] == 2
        assert m["tools"]["Read"] == 1
        assert m["categories"]["API: Matomo"] == 2
        assert m["categories"]["Read: knowledge"] == 1

    def test_tokens_from_conversation(self, two_prompt_conv):
        m = _original_metrics(two_prompt_conv)
        assert m["input_tokens"] == 40000
        assert m["output_tokens"] == 10000

    def test_msg_count(self, two_prompt_conv):
        m = _original_metrics(two_prompt_conv)
        assert m["msg_count"] == 8

    def test_single_prompt(self):
        msgs = [
            _msg("user", "hello", T0, id=1),
            _msg("assistant", "hi", T0 + timedelta(seconds=5), id=2),
        ]
        conv = Conversation(id="c2", messages=msgs)
        m = _original_metrics(conv)
        assert m["prompt_count"] == 1
        assert m["prompt_durations"] == [5.0]

    def test_malformed_tool_use_skipped(self):
        msgs = [
            _msg("user", "go", T0, id=1),
            _msg("tool_use", "not json {{{", T0 + timedelta(seconds=1), id=2),
            _msg("assistant", "done", T0 + timedelta(seconds=2), id=3),
        ]
        conv = Conversation(id="c3", messages=msgs)
        m = _original_metrics(conv)
        assert m["prompt_count"] == 1
        assert len(m["tools"]) == 0


class TestHistoryForPrompt:
    def test_first_prompt_has_empty_history(self, two_prompt_conv):
        prompt, history = _history_for_prompt(two_prompt_conv.messages, 0)
        assert prompt == "Quel est le trafic ?"
        assert history == []

    def test_second_prompt_gets_user_assistant_history(self, two_prompt_conv):
        prompt, history = _history_for_prompt(two_prompt_conv.messages, 1)
        assert prompt == "Compare avec février"
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Quel est le trafic ?"}
        assert history[1] == {"role": "assistant", "content": "Voici le trafic."}

    def test_tool_messages_excluded_from_history(self, two_prompt_conv):
        _, history = _history_for_prompt(two_prompt_conv.messages, 1)
        roles = {h["role"] for h in history}
        assert roles == {"user", "assistant"}


class TestTableRow:
    def test_formatting(self):
        row = _table_row(["A", "BB", "CCC"], [4, 4, 4])
        assert row == "   A    BB   CCC\n"

    def test_separator_row(self):
        row = _table_row(["──", "──"], [4, 4])
        assert "──" in row


@pytest.mark.parametrize(
    ("res", "substrs"),
    [
        (PromptResult(duration_s=1.0, events=3), ["✓", "1.0s", "3 events"]),
        (
            PromptResult(
                duration_s=2.0,
                events=1,
                tools=["Bash"],
                categories=["API: Matomo"],
                input_tokens=100,
                output_tokens=50,
                error="boom",
            ),
            ["✗", "API: Matomo", "ERR:", "boom"],
        ),
    ],
)
def test_run_prompt_line(res, substrs):
    line = _run_prompt_line(res)
    for s in substrs:
        assert s in line


def test_yield_summary_table_includes_totals():
    orig = {"prompt_durations": [10.0, 20.0], "total_s": 30.0}
    run_a = [PromptResult(duration_s=11.0), PromptResult(duration_s=21.0)]
    run_b = [PromptResult(duration_s=12.0), PromptResult(duration_s=22.0)]
    lines = _yield_summary_table(2, 2, orig, [run_a, run_b])
    text = "".join(lines)
    assert "RESULTS" in text and "TOTAL" in text
    assert "Stdev" in text


class TestBenchmarkRoute:
    @pytest.fixture
    def app_and_client(self, mocker):
        mocker.patch("web.benchmark.config")
        mocker.patch("web.benchmark.store")

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from web.benchmark import router
        from web.deps import get_current_user

        app = FastAPI()
        app.include_router(router)
        return app, TestClient(app), get_current_user

    def test_403_for_non_admin(self, app_and_client):
        app, client, dep = app_and_client
        from web.benchmark import config

        config.ADMIN_USERS = ["boss@test.com"]
        app.dependency_overrides[dep] = lambda: "nobody@test.com"
        resp = client.get("/benchmark/some-id")
        assert resp.status_code == 403

    def test_404_for_missing_conversation(self, app_and_client):
        app, client, dep = app_and_client
        from web.benchmark import config, store

        config.ADMIN_USERS = ["admin@test.com"]
        app.dependency_overrides[dep] = lambda: "admin@test.com"
        store.get_conversation.return_value = None
        resp = client.get("/benchmark/nonexistent")
        assert resp.status_code == 404

    def test_400_for_no_user_messages(self, app_and_client):
        app, client, dep = app_and_client
        from web.benchmark import config, store

        config.ADMIN_USERS = ["admin@test.com"]
        app.dependency_overrides[dep] = lambda: "admin@test.com"
        conv = Conversation(id="c1", messages=[_msg("assistant", "hi", T0)])
        store.get_conversation.return_value = conv
        resp = client.get("/benchmark/c1")
        assert resp.status_code == 400


class TestPromptResult:
    def test_defaults(self):
        r = PromptResult()
        assert r.duration_s == 0
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.tools == []
        assert r.error == ""

    def test_independent_lists(self):
        a = PromptResult()
        b = PromptResult()
        a.tools.append("Bash")
        assert b.tools == []
