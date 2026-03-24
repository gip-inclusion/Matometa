"""Tests for web/selftest.py — unit tests with mocked externals."""

import pytest

from web.selftest import Check, _fmt, _probe, _run_all_checks


class TestProbe:
    def test_ok_probe(self):
        c = _probe("test", lambda: (True, "all good"))
        assert c.ok is True
        assert c.detail == "all good"
        assert c.duration_ms >= 0

    def test_failing_probe(self):
        c = _probe("test", lambda: (False, "missing"))
        assert c.ok is False
        assert c.detail == "missing"

    def test_exception_is_caught(self):
        def boom():
            raise RuntimeError("kaboom")

        c = _probe("boom", boom)
        assert c.ok is False
        assert "kaboom" in c.detail

    def test_detail_truncated_to_120(self):
        def long_error():
            raise RuntimeError("x" * 200)

        c = _probe("trunc", long_error)
        assert len(c.detail) <= 120


class TestFmt:
    def test_ok_format(self):
        line = _fmt(Check("Foo", True, "v1.0", 42))
        assert "\u2705" in line
        assert "Foo" in line
        assert "v1.0" in line
        assert "42ms" in line

    def test_fail_format(self):
        line = _fmt(Check("Bar", False, "down"))
        assert "\u274c" in line
        assert "Bar" in line

    def test_no_detail(self):
        line = _fmt(Check("Baz", True))
        assert "\u2014" not in line


class TestRunAllChecks:
    def test_all_checks_produce_check_instances(self, mocker):
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
        mocker.patch("web.selftest._check_s3", return_value=(False, "not configured"))
        mocker.patch("web.selftest._check_matomo", return_value=(True, "v5.0"))
        mocker.patch("web.selftest._check_metabase_instance", return_value=(True, "healthy"))
        mocker.patch("web.selftest._check_notion", return_value=(False, "not set"))
        mocker.patch("web.selftest._check_grist", return_value=(False, "not set"))
        mocker.patch("web.selftest._check_livestorm", return_value=(False, "not set"))
        mocker.patch("web.selftest._check_slack", return_value=(False, "not set"))
        mocker.patch("lib._sources.list_instances", return_value=["stats"])

        checks = _run_all_checks()

        assert len(checks) >= 10
        assert all(isinstance(c, Check) for c in checks)
        passed = [c for c in checks if c.ok]
        failed = [c for c in checks if not c.ok]
        assert len(passed) >= 5
        assert len(failed) >= 4


class TestSelftestRoute:
    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from web.selftest import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_returns_text(self, mocker, client):
        mocker.patch(
            "web.selftest._run_all_checks",
            return_value=[
                Check("A", True, "ok", 1),
                Check("B", False, "down", 2),
            ],
        )
        resp = client.get("/selftest")

        assert resp.status_code == 503
        assert "text/plain" in resp.headers["content-type"]
        body = resp.text
        assert "1/2 OK" in body
        assert "\u2705 A" in body
        assert "\u274c B" in body

    def test_200_when_all_pass(self, mocker, client):
        mocker.patch(
            "web.selftest._run_all_checks",
            return_value=[Check("X", True, "fine", 1)],
        )
        resp = client.get("/selftest")
        assert resp.status_code == 200
        assert "1/1 OK" in resp.text
