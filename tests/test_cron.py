"""Tests for cron task discovery, execution, and database logging."""

import json
import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from web import config
from web.cron import (
    _parse_frontmatter,
    _is_enabled,
    discover_cron_tasks,
    find_task,
    run_cron_task,
    get_last_runs,
    get_app_runs,
    set_cron_enabled,
    DEFAULT_TIMEOUT,
)
from web.database import get_db, init_db


@pytest.fixture
def interactive_dir(tmp_path, monkeypatch):
    """Set up a temporary interactive directory with test apps."""
    d = tmp_path / "interactive"
    d.mkdir()
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir()
    monkeypatch.setattr(config, "INTERACTIVE_DIR", d)
    monkeypatch.setattr(config, "CRON_DIR", cron_dir)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    return d


@pytest.fixture
def db_setup(tmp_path, monkeypatch):
    """Set up a temporary database."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "SQLITE_PATH", db_path)
    monkeypatch.setattr(config, "DATABASE_URL", None)
    # Re-import to pick up the new path
    import web.database as db_mod
    monkeypatch.setattr(db_mod, "USE_POSTGRES", False)
    init_db()
    return db_path


def _create_app(interactive_dir, slug, cron_script=None, app_md=None):
    """Helper to create a test interactive app."""
    app_dir = interactive_dir / slug
    app_dir.mkdir()

    if app_md is None:
        app_md = f"---\ntitle: {slug}\n---\n"
    (app_dir / "APP.md").write_text(app_md)

    if cron_script is not None:
        (app_dir / "cron.py").write_text(cron_script)

    return app_dir


# =============================================================================
# Discovery tests
# =============================================================================

class TestParseFrontmatter:
    def test_no_file(self, tmp_path):
        assert _parse_frontmatter(tmp_path / "nonexistent" / "APP.md") == {}

    def test_no_cron_field(self, tmp_path):
        p = tmp_path / "APP.md"
        p.write_text("---\ntitle: Test\n---\n")
        assert _is_enabled(_parse_frontmatter(p)) is True

    def test_cron_true(self, tmp_path):
        p = tmp_path / "APP.md"
        p.write_text("---\ntitle: Test\ncron: true\n---\n")
        assert _is_enabled(_parse_frontmatter(p)) is True

    def test_cron_false(self, tmp_path):
        p = tmp_path / "APP.md"
        p.write_text("---\ntitle: Test\ncron: false\n---\n")
        assert _is_enabled(_parse_frontmatter(p)) is False

    def test_cron_no(self, tmp_path):
        p = tmp_path / "APP.md"
        p.write_text("---\ntitle: Test\ncron: no\n---\n")
        assert _is_enabled(_parse_frontmatter(p)) is False

    def test_cron_off(self, tmp_path):
        p = tmp_path / "APP.md"
        p.write_text("---\ntitle: Test\ncron: off\n---\n")
        assert _is_enabled(_parse_frontmatter(p)) is False

    def test_no_frontmatter(self, tmp_path):
        p = tmp_path / "APP.md"
        p.write_text("Just some text")
        assert _is_enabled(_parse_frontmatter(p)) is True

    def test_timeout_field(self, tmp_path):
        p = tmp_path / "CRON.md"
        p.write_text("---\ntimeout: 1200\n---\n")
        from web.cron import _get_timeout
        assert _get_timeout(_parse_frontmatter(p)) == 1200

    def test_schedule_field(self, tmp_path):
        p = tmp_path / "CRON.md"
        p.write_text("---\nschedule: weekly\n---\n")
        from web.cron import _get_schedule
        assert _get_schedule(_parse_frontmatter(p)) == "weekly"


class TestDiscoverCronTasks:
    def test_empty_dir(self, interactive_dir):
        assert discover_cron_tasks() == []

    def test_app_without_cron_py(self, interactive_dir):
        _create_app(interactive_dir, "no-cron")
        assert discover_cron_tasks() == []

    def test_app_with_cron_py(self, interactive_dir):
        _create_app(interactive_dir, "my-app", cron_script="print('hi')")
        tasks = discover_cron_tasks()
        assert len(tasks) == 1
        assert tasks[0]["slug"] == "my-app"
        assert tasks[0]["enabled"] is True

    def test_disabled_app(self, interactive_dir):
        _create_app(
            interactive_dir,
            "disabled-app",
            cron_script="print('hi')",
            app_md="---\ntitle: Disabled\ncron: false\n---\n",
        )
        tasks = discover_cron_tasks()
        assert len(tasks) == 1
        assert tasks[0]["slug"] == "disabled-app"
        assert tasks[0]["enabled"] is False

    def test_multiple_apps_sorted(self, interactive_dir):
        _create_app(interactive_dir, "beta", cron_script="pass")
        _create_app(interactive_dir, "alpha", cron_script="pass")
        tasks = discover_cron_tasks()
        assert [t["slug"] for t in tasks] == ["alpha", "beta"]

    def test_extracts_title(self, interactive_dir):
        _create_app(
            interactive_dir,
            "titled-app",
            cron_script="pass",
            app_md="---\ntitle: My Great App\n---\n",
        )
        tasks = discover_cron_tasks()
        assert tasks[0]["title"] == "My Great App"

    def test_nonexistent_dir(self, monkeypatch):
        monkeypatch.setattr(config, "INTERACTIVE_DIR", Path("/nonexistent"))
        monkeypatch.setattr(config, "CRON_DIR", Path("/nonexistent"))
        assert discover_cron_tasks() == []

    def test_system_tasks_come_first(self, interactive_dir, tmp_path, monkeypatch):
        """System tasks (cron/) are listed before app tasks (interactive/)."""
        cron_dir = tmp_path / "cron"
        monkeypatch.setattr(config, "CRON_DIR", cron_dir)

        # Create a system task
        sys_dir = cron_dir / "sys-task"
        sys_dir.mkdir(parents=True)
        (sys_dir / "cron.py").write_text("pass")
        (sys_dir / "CRON.md").write_text("---\ntitle: System Task\nschedule: weekly\n---\n")

        # Create an app task
        _create_app(interactive_dir, "app-task", cron_script="pass")

        tasks = discover_cron_tasks()
        assert len(tasks) == 2
        assert tasks[0]["slug"] == "sys-task"
        assert tasks[0]["tier"] == "system"
        assert tasks[0]["schedule"] == "weekly"
        assert tasks[1]["slug"] == "app-task"
        assert tasks[1]["tier"] == "app"


# =============================================================================
# Execution tests
# =============================================================================

class TestRunCronTask:
    def test_success(self, interactive_dir, db_setup):
        _create_app(interactive_dir, "good-app", cron_script="print('hello world')")
        result = run_cron_task("good-app", trigger="manual")
        assert result["status"] == "success"
        assert "hello world" in result["output"]
        assert result["duration_ms"] >= 0

    def test_failure_exit_code(self, interactive_dir, db_setup):
        _create_app(interactive_dir, "bad-app", cron_script="import sys; sys.exit(1)")
        result = run_cron_task("bad-app", trigger="manual")
        assert result["status"] == "failure"

    def test_stderr_captured(self, interactive_dir, db_setup):
        _create_app(
            interactive_dir,
            "stderr-app",
            cron_script="import sys; print('err', file=sys.stderr)",
        )
        result = run_cron_task("stderr-app", trigger="manual")
        assert "err" in result["output"]

    def test_nonexistent_app(self, interactive_dir, db_setup):
        result = run_cron_task("no-such-app")
        assert result["status"] == "failure"
        assert "not found" in result["output"]

    def test_writes_data_file(self, interactive_dir, db_setup):
        script = textwrap.dedent("""\
            import json
            with open('data.json', 'w') as f:
                json.dump({"updated": True}, f)
        """)
        _create_app(interactive_dir, "writer-app", cron_script=script)
        result = run_cron_task("writer-app")
        assert result["status"] == "success"

        data_file = interactive_dir / "writer-app" / "data.json"
        assert data_file.exists()
        assert json.loads(data_file.read_text())["updated"] is True

    def test_timeout(self, interactive_dir, db_setup):
        _create_app(
            interactive_dir,
            "slow-app",
            cron_script="import time; time.sleep(10)",
            app_md="---\ntitle: Slow\ntimeout: 1\n---\n",
        )
        result = run_cron_task("slow-app")
        assert result["status"] == "timeout"

    def test_records_in_database(self, interactive_dir, db_setup):
        _create_app(interactive_dir, "db-app", cron_script="print('ok')")
        run_cron_task("db-app", trigger="manual")

        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM cron_runs WHERE app_slug = ?", ("db-app",)
            ).fetchone()
            assert row is not None
            assert row["status"] == "success"
            assert row["trigger"] == "manual"

    def test_pythonpath_includes_project_root(self, interactive_dir, db_setup):
        script = textwrap.dedent("""\
            import sys
            print(sys.path)
        """)
        _create_app(interactive_dir, "path-app", cron_script=script)
        result = run_cron_task("path-app")
        assert result["status"] == "success"
        assert str(config.BASE_DIR) in result["output"]


# =============================================================================
# Database query tests
# =============================================================================

class TestGetLastRuns:
    def test_empty(self, interactive_dir, db_setup):
        assert get_last_runs() == {}

    def test_returns_latest(self, interactive_dir, db_setup):
        _create_app(interactive_dir, "multi-app", cron_script="print('run')")
        run_cron_task("multi-app")
        run_cron_task("multi-app")

        runs = get_last_runs(limit_per_app=1)
        assert "multi-app" in runs
        assert len(runs["multi-app"]) == 1

    def test_limit_per_app(self, interactive_dir, db_setup):
        _create_app(interactive_dir, "many-app", cron_script="print('x')")
        for _ in range(5):
            run_cron_task("many-app")

        runs = get_last_runs(limit_per_app=3)
        assert len(runs["many-app"]) == 3


class TestGetAppRuns:
    def test_empty(self, interactive_dir, db_setup):
        assert get_app_runs("nonexistent") == []

    def test_returns_runs(self, interactive_dir, db_setup):
        _create_app(interactive_dir, "log-app", cron_script="print('logged')")
        run_cron_task("log-app")
        runs = get_app_runs("log-app")
        assert len(runs) == 1
        assert runs[0]["status"] == "success"


# =============================================================================
# Toggle tests
# =============================================================================

class TestSetCronEnabled:
    def test_disable(self, interactive_dir):
        _create_app(interactive_dir, "toggle-app", cron_script="pass")
        assert set_cron_enabled("toggle-app", False) is True

        content = (interactive_dir / "toggle-app" / "APP.md").read_text()
        assert "cron: false" in content

    def test_enable(self, interactive_dir):
        _create_app(
            interactive_dir,
            "off-app",
            cron_script="pass",
            app_md="---\ntitle: Off\ncron: false\n---\n",
        )
        assert set_cron_enabled("off-app", True) is True

        content = (interactive_dir / "off-app" / "APP.md").read_text()
        assert "cron: true" in content

    def test_nonexistent_app(self, interactive_dir):
        assert set_cron_enabled("nope", True) is False

    def test_adds_field_when_missing(self, interactive_dir):
        _create_app(
            interactive_dir,
            "no-field",
            cron_script="pass",
            app_md="---\ntitle: No Field\n---\n",
        )
        set_cron_enabled("no-field", False)

        content = (interactive_dir / "no-field" / "APP.md").read_text()
        assert "cron: false" in content

    def test_roundtrip(self, interactive_dir):
        _create_app(interactive_dir, "rt-app", cron_script="pass")

        set_cron_enabled("rt-app", False)
        tasks = discover_cron_tasks()
        assert tasks[0]["enabled"] is False

        set_cron_enabled("rt-app", True)
        tasks = discover_cron_tasks()
        assert tasks[0]["enabled"] is True
