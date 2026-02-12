"""Cron runner for interactive app data refresh scripts.

Convention: any interactive app with a `cron.py` in its folder is cron-eligible.
The `cron:` field in APP.md controls whether it's enabled (default: true).

Usage:
    python -m web.cron              # run all enabled cron tasks
    python -m web.cron --app slug   # run one specific app
    python -m web.cron --list       # list discovered cron tasks
    python -m web.cron --dry-run    # show what would run
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config
from .database import get_db

# Timeout per script (seconds)
SCRIPT_TIMEOUT = 300  # 5 minutes

# Max output stored in DB (bytes)
MAX_OUTPUT_SIZE = 50_000


def _parse_cron_enabled(app_md_path: Path) -> bool:
    """Check if cron is enabled in APP.md front-matter.

    Returns True unless APP.md explicitly contains `cron: false`.
    """
    try:
        content = app_md_path.read_text()
    except OSError:
        return True

    if not content.startswith("---"):
        return True

    parts = content.split("---", 2)
    if len(parts) < 3:
        return True

    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip().lower() == "cron":
                return value.strip().lower() not in ("false", "no", "0", "off")

    return True


def set_cron_enabled(app_slug: str, enabled: bool) -> bool:
    """Toggle the `cron:` field in an app's APP.md.

    Returns True if the file was updated, False if app not found.
    """
    app_dir = config.INTERACTIVE_DIR / app_slug
    app_md = app_dir / "APP.md"
    if not app_md.exists():
        return False

    content = app_md.read_text()
    value_str = "true" if enabled else "false"

    if not content.startswith("---"):
        # No front-matter — prepend it
        content = f"---\ncron: {value_str}\n---\n{content}"
        app_md.write_text(content)
        return True

    parts = content.split("---", 2)
    if len(parts) < 3:
        return False

    lines = parts[1].strip().split("\n")
    found = False
    for i, line in enumerate(lines):
        if ":" in line:
            key, _ = line.split(":", 1)
            if key.strip().lower() == "cron":
                lines[i] = f"cron: {value_str}"
                found = True
                break

    if not found:
        lines.append(f"cron: {value_str}")

    content = "---\n" + "\n".join(lines) + "\n---" + parts[2]
    app_md.write_text(content)
    return True


def discover_cron_tasks() -> list[dict]:
    """Scan interactive apps for cron.py scripts.

    Returns list of dicts with keys: slug, path, cron_path, enabled.
    """
    tasks = []
    interactive_dir = config.INTERACTIVE_DIR
    if not interactive_dir.exists():
        return tasks

    for folder in sorted(interactive_dir.iterdir()):
        if not folder.is_dir():
            continue
        cron_script = folder / "cron.py"
        if not cron_script.exists():
            continue

        app_md = folder / "APP.md"
        enabled = _parse_cron_enabled(app_md)

        # Extract title from APP.md
        title = folder.name
        if app_md.exists():
            try:
                content = app_md.read_text()
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        for line in parts[1].strip().split("\n"):
                            if ":" in line:
                                key, value = line.split(":", 1)
                                if key.strip().lower() == "title":
                                    title = value.strip()
                                    break
            except OSError:
                pass

        tasks.append({
            "slug": folder.name,
            "title": title,
            "path": str(folder),
            "cron_path": str(cron_script),
            "enabled": enabled,
        })

    return tasks


def run_cron_task(slug: str, trigger: str = "scheduled") -> dict:
    """Run a single cron task by slug.

    Returns dict with: slug, status, output, duration_ms, started_at, finished_at.
    """
    cron_script = config.INTERACTIVE_DIR / slug / "cron.py"
    if not cron_script.exists():
        return {
            "slug": slug,
            "status": "failure",
            "output": f"cron.py not found in {slug}",
            "duration_ms": 0,
            "started_at": datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
        }

    started_at = datetime.now()
    start_time = time.monotonic()

    env = {
        **__import__("os").environ,
        "PYTHONPATH": str(config.BASE_DIR),
    }

    try:
        result = subprocess.run(
            [sys.executable, str(cron_script)],
            cwd=str(config.INTERACTIVE_DIR / slug),
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT,
            env=env,
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        finished_at = datetime.now()

        output = result.stdout
        if result.stderr:
            output += "\n--- stderr ---\n" + result.stderr
        output = output[:MAX_OUTPUT_SIZE]

        status = "success" if result.returncode == 0 else "failure"

    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        finished_at = datetime.now()
        status = "timeout"
        output = f"Script timed out after {SCRIPT_TIMEOUT}s"

    except Exception as e:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        finished_at = datetime.now()
        status = "failure"
        output = f"Error running script: {e}"

    run_result = {
        "slug": slug,
        "status": status,
        "output": output,
        "duration_ms": elapsed_ms,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }

    # Record in database
    _record_run(run_result, trigger)

    return run_result


def _record_run(result: dict, trigger: str):
    """Store a cron run result in the database."""
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO cron_runs (app_slug, started_at, finished_at, status, output, duration_ms, trigger)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    result["slug"],
                    result["started_at"],
                    result["finished_at"],
                    result["status"],
                    result["output"],
                    result["duration_ms"],
                    trigger,
                ),
            )
    except Exception as e:
        print(f"Warning: failed to record cron run: {e}", file=sys.stderr)


def get_last_runs(limit_per_app: int = 1) -> dict[str, list[dict]]:
    """Get the last N runs for each app slug.

    Returns dict mapping slug -> list of run dicts (newest first).
    """
    runs: dict[str, list[dict]] = {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM cron_runs
                   ORDER BY started_at DESC"""
            ).fetchall()

            for row in rows:
                slug = row["app_slug"]
                if slug not in runs:
                    runs[slug] = []
                if len(runs[slug]) < limit_per_app:
                    runs[slug].append({
                        "id": row["id"],
                        "app_slug": row["app_slug"],
                        "started_at": row["started_at"],
                        "finished_at": row["finished_at"],
                        "status": row["status"],
                        "output": row["output"],
                        "duration_ms": row["duration_ms"],
                        "trigger": row["trigger"],
                    })
    except Exception:
        pass
    return runs


def get_app_runs(slug: str, limit: int = 20) -> list[dict]:
    """Get recent runs for a specific app."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM cron_runs
                   WHERE app_slug = ?
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (slug, limit),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "app_slug": row["app_slug"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "status": row["status"],
                    "output": row["output"],
                    "duration_ms": row["duration_ms"],
                    "trigger": row["trigger"],
                }
                for row in rows
            ]
    except Exception:
        return []


def run_all(dry_run: bool = False) -> list[dict]:
    """Discover and run all enabled cron tasks."""
    tasks = discover_cron_tasks()
    results = []

    for task in tasks:
        if not task["enabled"]:
            if dry_run:
                print(f"  SKIP {task['slug']} (disabled)")
            continue

        if dry_run:
            print(f"  WOULD RUN {task['slug']}")
            continue

        print(f"  Running {task['slug']}...", end=" ", flush=True)
        result = run_cron_task(task["slug"], trigger="scheduled")
        print(f"{result['status']} ({result['duration_ms']}ms)")
        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(description="Run cron tasks for interactive apps")
    parser.add_argument("--app", help="Run a specific app by slug")
    parser.add_argument("--list", action="store_true", help="List all discovered cron tasks")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without executing")
    args = parser.parse_args()

    if args.list:
        tasks = discover_cron_tasks()
        if not tasks:
            print("No cron tasks found.")
            return
        for task in tasks:
            status = "enabled" if task["enabled"] else "DISABLED"
            print(f"  {task['slug']:30s} [{status}]  {task['cron_path']}")
        return

    if args.app:
        print(f"Running cron for {args.app}...")
        result = run_cron_task(args.app, trigger="manual")
        print(f"  Status: {result['status']} ({result['duration_ms']}ms)")
        if result["output"]:
            print(result["output"])
        return

    print("Running all cron tasks...")
    results = run_all(dry_run=args.dry_run)
    if not args.dry_run:
        ok = sum(1 for r in results if r["status"] == "success")
        fail = len(results) - ok
        print(f"Done: {ok} succeeded, {fail} failed")


if __name__ == "__main__":
    main()
