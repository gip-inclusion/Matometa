"""Tests for web/selftest.py."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.selftest import (
    SNAPSHOT_SEP,
    Check,
    _check_claude_code_ping,
    _check_claude_status_page,
    _fmt,
    _probe,
    _run_all_checks,
    router,
)


def _selftest_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize(
    ("json_payload", "expect_ok", "detail_substr", "also_in_detail"),
    [
        (
            {
                "status": {"indicator": "none", "description": "All Systems Operational"},
                "components": [
                    {"name": "Claude API (api.anthropic.com)", "status": "operational"},
                ],
            },
            True,
            "All Systems Operational",
            None,
        ),
        (
            {
                "status": {
                    "indicator": "minor",
                    "description": "Partially Degraded Service",
                },
                "components": [
                    {"name": "Claude Code", "status": "degraded_performance"},
                ],
            },
            False,
            "Partially Degraded",
            "Claude Code",
        ),
    ],
)
def test_claude_status_page_payload(mocker, json_payload, expect_ok, detail_substr, also_in_detail):
    mock_get = mocker.patch("web.selftest.requests.get")
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = json_payload
    mock_get.return_value = mock_resp

    ok, detail = _check_claude_status_page()

    assert ok is expect_ok
    assert detail_substr in detail
    if also_in_detail:
        assert also_in_detail in detail
    if expect_ok:
        mock_get.assert_called_once()
        assert mock_get.call_args[0][0] == "https://status.claude.com/api/v2/summary.json"


def test_claude_status_page_http_error(mocker):
    mocker.patch(
        "web.selftest.requests.get",
        return_value=mocker.MagicMock(status_code=503, text=""),
    )
    ok, detail = _check_claude_status_page()
    assert ok is False
    assert "503" in detail


def test_claude_status_page_invalid_json(mocker):
    mock_get = mocker.patch("web.selftest.requests.get")
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = json.JSONDecodeError("msg", "", 0)
    mock_get.return_value = mock_resp

    ok, detail = _check_claude_status_page()
    assert ok is False
    assert "invalid JSON" in detail


@pytest.mark.parametrize(
    ("subprocess_return", "expect_ok", "detail_check"),
    [
        (
            {"returncode": 0, "stdout": "pong\n", "stderr": ""},
            True,
            lambda d: d == "API OK",
        ),
        (
            {"returncode": 1, "stdout": "", "stderr": "rate limited"},
            False,
            lambda d: "rate" in d,
        ),
    ],
)
def test_claude_code_ping(mocker, subprocess_return, expect_ok, detail_check):
    mocker.patch(
        "web.selftest.subprocess.run",
        return_value=mocker.MagicMock(**subprocess_return),
    )
    ok, detail = _check_claude_code_ping()
    assert ok is expect_ok
    assert detail_check(detail)


@pytest.mark.parametrize(
    ("fn", "expect_ok", "expect_detail_substr"),
    [
        (lambda: (True, "all good"), True, "all good"),
        (lambda: (False, "missing"), False, "missing"),
    ],
)
def test_probe_ok_and_fail(fn, expect_ok, expect_detail_substr):
    c = _probe("test", fn)
    assert c.ok is expect_ok
    assert expect_detail_substr in c.detail
    assert c.duration_ms >= 0


def test_probe_exception():
    def boom():
        raise RuntimeError("kaboom")

    c = _probe("boom", boom)
    assert c.ok is False
    assert "kaboom" in c.detail


def test_probe_detail_truncated():
    def long_error():
        raise RuntimeError("x" * 200)

    c = _probe("trunc", long_error)
    assert len(c.detail) <= 120


@pytest.mark.parametrize(
    ("check", "expect_ok_glyph", "expect_fail_glyph", "extra_assert"),
    [
        (
            Check("Foo", True, "v1.0", 42),
            "\u2705",
            None,
            lambda line: "42ms" in line and "v1.0" in line,
        ),
        (
            Check("Bar", False, "down"),
            None,
            "\u274c",
            lambda line: "down" in line,
        ),
        (
            Check("Baz", True),
            "\u2705",
            None,
            lambda line: "\u2014" not in line,
        ),
    ],
)
def test_fmt(check, expect_ok_glyph, expect_fail_glyph, extra_assert):
    line = _fmt(check)
    if expect_ok_glyph:
        assert expect_ok_glyph in line
    if expect_fail_glyph:
        assert expect_fail_glyph in line
    assert check.name in line
    extra_assert(line)


def test_run_all_checks_produces_check_instances(mocker):
    mock_getenv = mocker.patch("web.selftest.os.getenv")
    mock_head = mocker.patch("web.selftest.requests.head")
    mock_get = mocker.patch("web.selftest.requests.get")
    mock_subprocess = mocker.patch("web.selftest.subprocess.run")
    mock_config = mocker.patch("web.selftest.config")
    mock_config.ADMIN_USERS = ["admin@localhost"]
    mock_config.USE_S3 = False
    mock_config.CLAUDE_CLI = "claude"
    mock_getenv.return_value = None

    mock_subprocess.return_value = mocker.MagicMock(returncode=0, stdout="1.0.0\n", stderr="")

    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = {"value": "5.0"}
    mock_get.return_value = mock_resp
    mock_head.return_value = mocker.MagicMock(status_code=200)

    mocker.patch("web.selftest._check_postgresql", return_value=(True, ""))
    mocker.patch("web.selftest._check_admin_users", return_value=(True, "1 configured"))
    mocker.patch("web.selftest._check_process_manager", return_value=(True, "heartbeat OK"))
    mocker.patch("web.selftest._check_conversation_roundtrip", return_value=(True, "OK"))
    mocker.patch("web.selftest._check_claude_cli", return_value=(True, "1.0.0"))
    mocker.patch("web.selftest._check_claude_status_page", return_value=(True, "page OK"))
    mocker.patch("web.selftest._check_claude_code_ping", return_value=(True, "API OK"))
    mocker.patch("web.selftest._check_s3", return_value=(False, "not configured"))
    mocker.patch("web.selftest._check_matomo", return_value=(True, "v5.0"))
    mocker.patch("web.selftest._check_metabase_instance", return_value=(True, "healthy"))
    mocker.patch("web.selftest._check_notion", return_value=(False, "not set"))
    mocker.patch("web.selftest._check_grist", return_value=(False, "not set"))
    mocker.patch("web.selftest._check_livestorm", return_value=(False, "not set"))
    mocker.patch("web.selftest._check_slack", return_value=(False, "not set"))
    mocker.patch("lib._sources.list_instances", return_value=["stats"])

    checks = _run_all_checks()

    assert len(checks) >= 12
    assert all(isinstance(c, Check) for c in checks)
    passed = [c for c in checks if c.ok]
    failed = [c for c in checks if not c.ok]
    assert len(passed) >= 5
    assert len(failed) >= 4


@pytest.mark.parametrize(
    ("specs", "expect_body_parts"),
    [
        (
            [
                ("A", lambda: (True, "ok")),
                ("B", lambda: (False, "down")),
            ],
            ["1/2 OK", "(1 failed)", "\u2705 A", "\u274c B"],
        ),
        (
            [("X", lambda: (True, "fine"))],
            ["1/1 OK"],
        ),
    ],
)
def test_selftest_plain_responses(mocker, specs, expect_body_parts):
    mocker.patch("web.selftest._check_specs", return_value=specs)
    resp = _selftest_client().get("/selftest")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    for part in expect_body_parts:
        assert part in resp.text


def test_selftest_plain_stream_separates_snapshots(mocker):
    mocker.patch(
        "web.selftest._check_specs",
        return_value=[
            ("A", lambda: (True, "ok")),
            ("B", lambda: (True, "ok")),
        ],
    )
    resp = _selftest_client().get("/selftest")
    assert resp.status_code == 200
    assert resp.text.count(SNAPSHOT_SEP) == 3


def test_selftest_accept_html(mocker):
    mocker.patch(
        "web.selftest._check_specs",
        return_value=[("X", lambda: (True, "fine"))],
    )
    resp = _selftest_client().get("/selftest", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    text = resp.text
    assert "fetch" in text and "text/plain" in text
    assert "split" in text and "pre" in text
