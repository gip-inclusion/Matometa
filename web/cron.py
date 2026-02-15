"""Cron runner for data refresh scripts.

Two-tier discovery:
- System tasks: checked into repo under cron/*/cron.py (CRON.md for metadata)
- App tasks: per-deployment in data/interactive/*/cron.py (APP.md for metadata)

Metadata fields (in CRON.md or APP.md front-matter):
- cron: true/false (default: true)
- timeout: seconds (default: 300)
- schedule: daily/weekly (default: daily)
- title: display name

Usage:
    python -m web.cron              # run all enabled cron tasks due today
    python -m web.cron --app slug   # run one specific task (ignores schedule)
    python -m web.cron --list       # list discovered cron tasks
    python -m web.cron --dry-run    # show what would run
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config
from .database import get_db

# Defaults
DEFAULT_TIMEOUT = 300  # 5 minutes
MAX_OUTPUT_SIZE = 50_000


def _parse_frontmatter(md_path: Path) -> dict:
    """Parse YAML front-matter from a markdown file.

    Returns dict of key-value pairs. Returns {} if no front-matter.
    """
    try:
        content = md_path.read_text()
    except OSError:
        return {}

    if not content.startswith("---"):
        return {}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}

    meta = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip()
    return meta


def _is_enabled(meta: dict) -> bool:
    return meta.get("cron", "true").lower() not in ("false", "no", "0", "off")


def _get_timeout(meta: dict) -> int:
    try:
        return int(meta["timeout"])
    except (KeyError, ValueError):
        return DEFAULT_TIMEOUT


def _get_schedule(meta: dict) -> str:
    return meta.get("schedule", "daily").lower()


def _is_due(schedule: str) -> bool:
    """Check if a task with the given schedule should run today."""
    if schedule == "daily":
        return True
    if schedule == "weekly":
        return datetime.now().weekday() == 0  # Monday
    return True


def set_cron_enabled(app_slug: str, enabled: bool) -> bool:
    """Toggle the `cron:` field in a task's metadata file.

    Checks both system (CRON.md) and app (APP.md) locations.
    Returns True if the file was updated, False if not found.
    """
    # Try system task first, then app task
    for md_path in [
        config.CRON_DIR / app_slug / "CRON.md",
        config.INTERACTIVE_DIR / app_slug / "APP.md",
    ]:
        if not md_path.exists():
            continue

        content = md_path.read_text()
        value_str = "true" if enabled else "false"

        if not content.startswith("---"):
            content = f"---\ncron: {value_str}\n---\n{content}"
            md_path.write_text(content)
            return True

        parts = content.split("---", 2)
        if len(parts) < 3:
            continue

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
        md_path.write_text(content)
        return True

    return False


def _discover_from_dir(base_dir: Path, md_name: str, tier: str) -> list[dict]:
    """Discover cron tasks from a directory.

    Args:
        base_dir: Parent directory to scan (e.g. cron/ or data/interactive/)
        md_name: Metadata filename to look for (CRON.md or APP.md)
        tier: "system" or "app"
    """
    tasks = []
    if not base_dir.exists():
        return tasks

    for folder in sorted(base_dir.iterdir()):
        if not folder.is_dir():
            continue
        cron_script = folder / "cron.py"
        if not cron_script.exists():
            continue

        meta = _parse_frontmatter(folder / md_name)

        tasks.append({
            "slug": folder.name,
            "title": meta.get("title", folder.name),
            "tier": tier,
            "path": str(folder),
            "cron_path": str(cron_script),
            "enabled": _is_enabled(meta),
            "timeout": _get_timeout(meta),
            "schedule": _get_schedule(meta),
        })

    return tasks


def discover_cron_tasks() -> list[dict]:
    """Discover all cron tasks from both tiers.

    System tasks (cron/) come first, then app tasks (data/interactive/).
    """
    tasks = _discover_from_dir(config.CRON_DIR, "CRON.md", "system")
    tasks += _discover_from_dir(config.INTERACTIVE_DIR, "APP.md", "app")
    return tasks


def find_task(slug: str) -> dict | None:
    """Find a task by slug across both tiers."""
    for task in discover_cron_tasks():
        if task["slug"] == slug:
            return task
    return None


def run_cron_task(slug: str, trigger: str = "scheduled") -> dict:
    """Run a single cron task by slug.

    Returns dict with: slug, status, output, duration_ms, started_at, finished_at.
    """
    task = find_task(slug)
    if not task:
        return {
            "slug": slug,
            "status": "failure",
            "output": f"cron task not found: {slug}",
            "duration_ms": 0,
            "started_at": datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
        }

    timeout = task["timeout"]
    cron_script = task["cron_path"]

    started_at = datetime.now()
    start_time = time.monotonic()

    env = {
        **os.environ,
        "PYTHONPATH": str(config.BASE_DIR),
    }

    try:
        result = subprocess.run(
            [sys.executable, cron_script],
            cwd=task["path"],
            capture_output=True,
            text=True,
            timeout=timeout,
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
        output = f"Script timed out after {timeout}s"

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
    """Get the last N runs for each app slug."""
    runs: dict[str, list[dict]] = {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM cron_runs ORDER BY started_at DESC"
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
    except Exception as e:
        print(f"Warning: failed to read cron runs: {e}", file=sys.stderr)
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
    except Exception as e:
        print(f"Warning: failed to read app runs: {e}", file=sys.stderr)
        return []


def run_all(dry_run: bool = False) -> list[dict]:
    """Discover and run all enabled cron tasks that are due today."""
    tasks = discover_cron_tasks()
    results = []

    for task in tasks:
        if not task["enabled"]:
            if dry_run:
                print(f"  SKIP {task['slug']} (disabled)")
            continue

        if not _is_due(task["schedule"]):
            if dry_run:
                print(f"  SKIP {task['slug']} (schedule: {task['schedule']}, not due)")
            continue

        if dry_run:
            sched = f" [{task['schedule']}]" if task["schedule"] != "daily" else ""
            print(f"  WOULD RUN {task['slug']}{sched} (timeout: {task['timeout']}s)")
            continue

        print(f"  Running {task['slug']}...", end=" ", flush=True)
        result = run_cron_task(task["slug"], trigger="scheduled")
        print(f"{result['status']} ({result['duration_ms']}ms)")
        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(description="Run cron tasks")
    parser.add_argument("--app", help="Run a specific task by slug (ignores schedule)")
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
            sched = task["schedule"]
            tier = task["tier"]
            print(f"  {task['slug']:30s} [{status}] {sched:8s} {tier:6s}  {task['cron_path']}")
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
