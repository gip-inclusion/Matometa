"""Tests for cron task discovery, execution, and database logging."""

import json
import textwrap
from pathlib import Path

import pytest

from web import config
from web.cron import (
    _is_enabled,
    _parse_frontmatter,
    discover_cron_tasks,
    get_app_runs,
    get_last_runs,
    run_cron_task,
    set_cron_enabled,
)
from web.database import get_db, init_db


@pytest.fixture
def interactive_dir(tmp_path, monkeypatch):
    d = tmp_path / "interactive"
    d.mkdir()
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir()
    monkeypatch.setattr(config, "INTERACTIVE_DIR", d)
    monkeypatch.setattr(config, "CRON_DIR", cron_dir)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "USE_S3", False)
    return d


@pytest.fixture
def db_setup(monkeypatch):
    init_db()
    yield

    from web.db import get_db

    with get_db() as conn:
        conn.execute_raw("""
            TRUNCATE TABLE messages, conversation_tags, report_tags,
                uploaded_files, cron_runs, pinned_items, pm_commands,
                pm_heartbeat, reports, conversations, tags, schema_version
                CASCADE;
        """)


def _create_app(interactive_dir, slug, cron_script=None, app_md=None):
    app_dir = interactive_dir / slug
    app_dir.mkdir()

    if app_md is None:
        app_md = f"---\ntitle: {slug}\n---\n"
    (app_dir / "APP.md").write_text(app_md)

    if cron_script is not None:
        (app_dir / "cron.py").write_text(cron_script)

    return app_dir


class TestParseFrontmatter:
    def test_no_file(self, tmp_path):
        assert _parse_frontmatter(tmp_path / "nonexistent" / "APP.md") == {}

    @pytest.mark.parametrize(
        "body,expected",
        [
            ("---\ntitle: Test\n---\n", True),
            ("---\ntitle: Test\ncron: true\n---\n", True),
            ("---\ntitle: Test\ncron: false\n---\n", False),
            ("---\ntitle: Test\ncron: no\n---\n", False),
            ("---\ntitle: Test\ncron: off\n---\n", False),
        ],
    )
    def test_cron_enabled_from_frontmatter(self, tmp_path, body, expected):
        p = tmp_path / "APP.md"
        p.write_text(body)
        assert _is_enabled(_parse_frontmatter(p)) is expected

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
            row = conn.execute("SELECT * FROM cron_runs WHERE app_slug = %s", ("db-app",)).fetchone()
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


@pytest.fixture
def s3_cron_env(tmp_path, monkeypatch):
    """Simulate an S3-backed server: no local interactive dir, USE_S3=True."""
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir()
    interactive_dir = tmp_path / "interactive"
    # Intentionally NOT creating interactive_dir — mimics the server
    monkeypatch.setattr(config, "INTERACTIVE_DIR", interactive_dir)
    monkeypatch.setattr(config, "CRON_DIR", cron_dir)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "USE_S3", True)
    return {"cron_dir": cron_dir, "interactive_dir": interactive_dir}


def _mock_s3_app(slug, cron_script="print('hello')", app_md=None):
    if app_md is None:
        app_md = f"---\ntitle: {slug}\n---\n"
    return {
        "slug": slug,
        "files": {
            f"{slug}/cron.py": cron_script.encode(),
            f"{slug}/APP.md": app_md.encode(),
        },
    }


def _make_s3_mocks(apps: list[dict]):
    """Create mock functions for web.s3 that serve the given apps.

    Returns a dict of {function_name: mock} to use with patch.
    """
    all_files = {}
    for app in apps:
        all_files.update(app["files"])
    slugs = [app["slug"] for app in apps]

    def mock_list_directories(prefix=""):
        return sorted(slugs)

    def mock_file_exists(path):
        return path in all_files

    def mock_download_file(path):
        return all_files.get(path)

    def mock_list_files(prefix=""):
        results = []
        for key, content in all_files.items():
            if key.startswith(prefix):
                results.append({"path": key, "size": len(content), "last_modified": None})
        return results

    def mock_upload_file(path, content, content_type=None):
        all_files[path] = content
        return True

    return {
        "list_directories": mock_list_directories,
        "file_exists": mock_file_exists,
        "download_file": mock_download_file,
        "list_files": mock_list_files,
        "upload_file": mock_upload_file,
        "_all_files": all_files,  # for assertions
    }


class TestDiscoverS3:
    def test_discovers_s3_apps(self, mocker, s3_cron_env):
        """When USE_S3 is True and S3 has apps with cron.py, they're discovered."""
        mocks = _make_s3_mocks([_mock_s3_app("my-s3-app")])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        tasks = discover_cron_tasks()
        assert len(tasks) == 1
        assert tasks[0]["slug"] == "my-s3-app"
        assert tasks[0]["tier"] == "app"

    def test_s3_app_skipped_without_cron_py(self, mocker, s3_cron_env):
        """S3 directories without cron.py are not discovered."""
        app = _mock_s3_app("no-cron-app")
        del app["files"]["no-cron-app/cron.py"]
        mocks = _make_s3_mocks([app])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        tasks = discover_cron_tasks()
        assert len(tasks) == 0

    def test_s3_app_metadata_parsed(self, mocker, s3_cron_env):
        """APP.md front-matter is parsed from S3."""
        app = _mock_s3_app(
            "titled-app",
            app_md="---\ntitle: My S3 App\ntimeout: 600\nschedule: weekly\n---\n",
        )
        mocks = _make_s3_mocks([app])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        tasks = discover_cron_tasks()
        assert tasks[0]["title"] == "My S3 App"
        assert tasks[0]["timeout"] == 600
        assert tasks[0]["schedule"] == "weekly"

    def test_s3_disabled_app(self, mocker, s3_cron_env):
        """Apps with cron: false in S3 APP.md are marked disabled."""
        app = _mock_s3_app(
            "off-app",
            app_md="---\ntitle: Off\ncron: false\n---\n",
        )
        mocks = _make_s3_mocks([app])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        tasks = discover_cron_tasks()
        assert tasks[0]["enabled"] is False

    def test_s3_and_system_crons_merged(self, mocker, s3_cron_env):
        """System crons from filesystem + S3 app crons all appear."""
        sys_dir = s3_cron_env["cron_dir"] / "sys-task"
        sys_dir.mkdir()
        (sys_dir / "cron.py").write_text("pass")
        (sys_dir / "CRON.md").write_text("---\ntitle: System\n---\n")

        mocks = _make_s3_mocks([_mock_s3_app("s3-app")])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        tasks = discover_cron_tasks()
        assert len(tasks) == 2
        assert tasks[0]["tier"] == "system"
        assert tasks[0]["slug"] == "sys-task"
        assert tasks[1]["tier"] == "app"
        assert tasks[1]["slug"] == "s3-app"

    def test_s3_multiple_apps_sorted(self, mocker, s3_cron_env):
        """S3 apps are returned in sorted order."""
        mocks = _make_s3_mocks(
            [
                _mock_s3_app("zeta-app"),
                _mock_s3_app("alpha-app"),
            ]
        )
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        tasks = discover_cron_tasks()
        assert [t["slug"] for t in tasks] == ["alpha-app", "zeta-app"]

    def test_no_s3_discovery_when_use_s3_false(self, interactive_dir, monkeypatch):
        """When USE_S3 is False, S3 is not queried (local-only discovery)."""
        monkeypatch.setattr(config, "USE_S3", False)
        tasks = discover_cron_tasks()
        assert tasks == []


class TestRunS3CronTask:
    def test_executes_s3_script(self, mocker, s3_cron_env, db_setup):
        """S3 cron script is downloaded, executed, and output captured."""
        app = _mock_s3_app("s3-runner", cron_script="print('s3 hello')")
        mocks = _make_s3_mocks([app])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        mocker.patch("web.cron.s3.list_files", side_effect=mocks["list_files"])
        mocker.patch("web.cron.s3.upload_file", side_effect=mocks["upload_file"])
        result = run_cron_task("s3-runner", trigger="manual")
        assert result["status"] == "success"
        assert "s3 hello" in result["output"]

    def test_s3_script_failure(self, mocker, s3_cron_env, db_setup):
        """S3 cron script failure is captured."""
        app = _mock_s3_app("s3-fail", cron_script="import sys; sys.exit(1)")
        mocks = _make_s3_mocks([app])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        mocker.patch("web.cron.s3.list_files", side_effect=mocks["list_files"])
        mocker.patch("web.cron.s3.upload_file", side_effect=mocks["upload_file"])
        result = run_cron_task("s3-fail", trigger="manual")
        assert result["status"] == "failure"

    def test_s3_script_uploads_output(self, mocker, s3_cron_env, db_setup):
        script = textwrap.dedent("""\
            import json
            from pathlib import Path
            Path("data.json").write_text(json.dumps({"updated": True}))
            print("done")
        """)
        app = _mock_s3_app("s3-writer", cron_script=script)
        mocks = _make_s3_mocks([app])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        mocker.patch("web.cron.s3.list_files", side_effect=mocks["list_files"])
        mocker.patch("web.cron.s3.upload_file", side_effect=mocks["upload_file"])
        result = run_cron_task("s3-writer", trigger="manual")
        assert result["status"] == "success"
        assert "s3-writer/data.json" in mocks["_all_files"]
        uploaded = json.loads(mocks["_all_files"]["s3-writer/data.json"])
        assert uploaded["updated"] is True

    def test_s3_script_has_pythonpath(self, mocker, s3_cron_env, db_setup):
        """S3 cron script has PYTHONPATH set to project root."""
        script = textwrap.dedent("""\
            import sys
            print(sys.path)
        """)
        app = _mock_s3_app("s3-path", cron_script=script)
        mocks = _make_s3_mocks([app])
        mocker.patch("web.cron.s3.list_directories", side_effect=mocks["list_directories"])
        mocker.patch("web.cron.s3.file_exists", side_effect=mocks["file_exists"])
        mocker.patch("web.cron.s3.download_file", side_effect=mocks["download_file"])
        mocker.patch("web.cron.s3.list_files", side_effect=mocks["list_files"])
        mocker.patch("web.cron.s3.upload_file", side_effect=mocks["upload_file"])
        result = run_cron_task("s3-path", trigger="manual")
        assert result["status"] == "success"
        assert str(config.BASE_DIR) in result["output"]
