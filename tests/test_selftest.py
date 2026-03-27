"""Tests for web/selftest.py — unit tests with mocked externals."""

import pytest

from web.config import BASE_DIR
from web.selftest import Check, run_selftest_checks


def mock_db_context(mocker):
    mock_conn = mocker.MagicMock()

    def exec_side_effect(sql, *args):
        q = str(sql)
        r = mocker.MagicMock()
        if "SELECT 1" in q:
            r.fetchone.return_value = {"ok": 1}
        elif "DISTINCT user_id" in q:
            r.fetchall.return_value = [{"user_id": "admin@localhost"}]
        else:
            r.fetchone.return_value = None
            r.fetchall.return_value = []
        return r

    mock_conn.execute.side_effect = exec_side_effect
    mock_cm = mocker.MagicMock()
    mock_cm.__enter__.return_value = mock_conn
    mock_cm.__exit__.return_value = None
    return mock_cm


class TestRunSelftestChecks:
    def test_all_checks_produce_check_instances(self, mocker):
        mock_getenv = mocker.patch("web.selftest.os.getenv")
        mock_head = mocker.patch("web.selftest.requests.head")
        mock_get = mocker.patch("web.selftest.requests.get")
        mock_subprocess = mocker.patch("web.selftest.subprocess.run")
        mock_config = mocker.patch("web.selftest.config")
        mock_config.BASE_DIR = BASE_DIR
        mock_config.ADMIN_USERS = ["admin@localhost"]
        mock_config.USE_S3 = False
        mock_config.CLAUDE_CLI = "claude"
        mock_getenv.return_value = None

        mock_subprocess.return_value = mocker.MagicMock(returncode=0, stdout="1.0.0\n", stderr="")

        mock_resp = mocker.MagicMock(status_code=200)
        mock_resp.json.return_value = {"value": "5.0"}
        mock_get.return_value = mock_resp
        mock_head.return_value = mocker.MagicMock(status_code=200)

        mocker.patch("web.selftest.get_db", return_value=mock_db_context(mocker))
        mock_store = mocker.patch("web.selftest.store")
        mock_store.is_pm_alive.return_value = True
        mock_conv = mocker.MagicMock()
        mock_conv.id = "selftest-conv"
        mock_store.create_conversation.return_value = mock_conv
        mock_store.get_messages.return_value = [{"role": "user", "content": "x"}]
        mocker.patch("lib._sources.list_instances", return_value=["stats"])

        checks = run_selftest_checks()

        assert len(checks) >= 10
        assert all(isinstance(c, Check) for c in checks)
        claude_cli = next(c for c in checks if c.name == "Claude CLI")
        assert claude_cli.ok, claude_cli.detail
        assert "skills:" in claude_cli.detail
        passed = [c for c in checks if c.ok]
        failed = [c for c in checks if not c.ok]
        assert len(passed) >= 5
        assert len(failed) >= 4

    def test_probe_catches_exception_from_check(self, mocker):
        mock_getenv = mocker.patch("web.selftest.os.getenv")
        mock_head = mocker.patch("web.selftest.requests.head")
        mock_get = mocker.patch("web.selftest.requests.get")
        mock_subprocess = mocker.patch("web.selftest.subprocess.run")
        mock_config = mocker.patch("web.selftest.config")
        mock_config.BASE_DIR = BASE_DIR
        mock_config.ADMIN_USERS = ["admin@localhost"]
        mock_config.USE_S3 = False
        mock_config.CLAUDE_CLI = "claude"
        mock_getenv.return_value = None
        mock_subprocess.return_value = mocker.MagicMock(returncode=0, stdout="x\n", stderr="")
        mock_resp = mocker.MagicMock(status_code=200)
        mock_resp.json.return_value = {"value": "5.0"}
        mock_get.return_value = mock_resp
        mock_head.return_value = mocker.MagicMock(status_code=200)

        def boom_conn():
            raise RuntimeError("x" * 200)

        mock_cm = mocker.MagicMock()
        mock_cm.__enter__ = boom_conn
        mock_cm.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch("web.selftest.get_db", return_value=mock_cm)
        mocker.patch("web.selftest.store")
        mocker.patch("lib._sources.list_instances", return_value=[])

        checks = run_selftest_checks()
        pg = next(c for c in checks if c.name == "PostgreSQL")
        assert pg.ok is False
        assert len(pg.detail) <= 120


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
            "web.selftest.run_selftest_checks",
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
            "web.selftest.run_selftest_checks",
            return_value=[Check("X", True, "fine", 1)],
        )
        resp = client.get("/selftest")
        assert resp.status_code == 200
        assert "1/1 OK" in resp.text
