"""Cron runner for data refresh scripts."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import config, s3
from .database import get_db

# Defaults
DEFAULT_TIMEOUT = 300  # 5 minutes
MAX_OUTPUT_SIZE = 50_000


def parse_frontmatter_text(content: str) -> dict:
    """Parse YAML front-matter from a string.

    Returns dict of key-value pairs. Returns {} if no front-matter.
    """
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


def parse_frontmatter(md_path: Path) -> dict:
    """Parse YAML front-matter from a markdown file.

    Returns dict of key-value pairs. Returns {} if no front-matter.
    """
    try:
        content = md_path.read_text()
    except OSError:
        return {}

    return parse_frontmatter_text(content)


def is_enabled(meta: dict) -> bool:
    return meta.get("cron", "true").lower() not in ("false", "no", "0", "off")


def get_timeout(meta: dict) -> int:
    try:
        return int(meta["timeout"])
    except (KeyError, ValueError):
        return DEFAULT_TIMEOUT


def get_schedule(meta: dict) -> str:
    return meta.get("schedule", "daily").lower()


def is_due(schedule: str) -> bool:
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


def discover_from_dir(base_dir: Path, md_name: str, tier: str) -> list[dict]:
    """Discover cron tasks from a directory."""
    tasks = []
    if not base_dir.exists():
        return tasks

    for folder in sorted(base_dir.iterdir()):
        if not folder.is_dir():
            continue
        cron_script = folder / "cron.py"
        if not cron_script.exists():
            continue

        meta = parse_frontmatter(folder / md_name)

        tasks.append(
            {
                "slug": folder.name,
                "title": meta.get("title", folder.name),
                "tier": tier,
                "path": str(folder),
                "cron_path": str(cron_script),
                "enabled": is_enabled(meta),
                "timeout": get_timeout(meta),
                "schedule": get_schedule(meta),
            }
        )

    return tasks


def discover_from_s3() -> list[dict]:
    """Discover cron tasks from S3-stored interactive apps."""
    tasks = []
    for slug in s3.list_directories():
        if not s3.file_exists(f"{slug}/cron.py"):
            continue

        # Parse APP.md metadata from S3
        md_bytes = s3.download_file(f"{slug}/APP.md")
        meta = parse_frontmatter_text(md_bytes.decode()) if md_bytes else {}

        tasks.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "tier": "app",
                "source": "s3",
                "path": slug,  # S3 prefix, not a local path
                "cron_path": f"{slug}/cron.py",
                "enabled": is_enabled(meta),
                "timeout": get_timeout(meta),
                "schedule": get_schedule(meta),
            }
        )

    return tasks


def discover_cron_tasks() -> list[dict]:
    """Discover all cron tasks from all tiers.

    System tasks (cron/) come first, then app tasks (data/interactive/ or S3).
    """
    tasks = discover_from_dir(config.CRON_DIR, "CRON.md", "system")
    if config.USE_S3:
        tasks += discover_from_s3()
    else:
        tasks += discover_from_dir(config.INTERACTIVE_DIR, "APP.md", "app")
    return tasks


def find_task(slug: str) -> dict | None:
    for task in discover_cron_tasks():
        if task["slug"] == slug:
            return task
    return None


def prepare_s3_workdir(slug: str) -> Path:
    workdir = Path(tempfile.mkdtemp(prefix=f"cron-{slug}-"))
    for entry in s3.list_files(f"{slug}/"):
        rel_path = entry["path"]
        # rel_path is like "slug/cron.py" — strip the slug prefix
        local_name = rel_path[len(slug) + 1 :]
        if not local_name or ".." in local_name:
            continue
        content = s3.download_file(rel_path)
        if content is not None:
            local_file = (workdir / local_name).resolve()
            # Path traversal protection
            try:
                local_file.relative_to(workdir.resolve())
            except ValueError:
                continue
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(content)
    return workdir


def upload_s3_results(slug: str, workdir: Path):
    workdir_resolved = workdir.resolve()
    for path in workdir.rglob("*"):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(workdir_resolved)
        except ValueError:
            continue
        rel = path.relative_to(workdir)
        s3_key = f"{slug}/{rel}"
        s3.upload_file(s3_key, path.read_bytes())


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

    is_s3 = task.get("source") == "s3"
    timeout = task["timeout"]
    workdir = None

    started_at = datetime.now()
    start_time = time.monotonic()

    env = {
        **os.environ,
        "PYTHONPATH": str(config.BASE_DIR),
    }

    try:
        if is_s3:
            workdir = prepare_s3_workdir(slug)
            cron_script = str(workdir / "cron.py")
            cwd = str(workdir)
        else:
            cron_script = task["cron_path"]
            cwd = task["path"]

        result = subprocess.run(
            [sys.executable, cron_script],
            cwd=cwd,
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

        if is_s3 and status == "success" and workdir:
            upload_s3_results(slug, workdir)

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

    finally:
        if workdir and workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)

    run_result = {
        "slug": slug,
        "status": status,
        "output": output,
        "duration_ms": elapsed_ms,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }

    record_run(run_result, trigger)
    return run_result


def record_run(result: dict, trigger: str):
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO cron_runs (app_slug, started_at, finished_at, status, output, duration_ms, trigger)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
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
    runs: dict[str, list[dict]] = {}
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM cron_runs ORDER BY started_at DESC").fetchall()

            for row in rows:
                slug = row["app_slug"]
                if slug not in runs:
                    runs[slug] = []
                if len(runs[slug]) < limit_per_app:
                    runs[slug].append(
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
                    )
    except Exception as e:
        print(f"Warning: failed to read cron runs: {e}", file=sys.stderr)
    return runs


def get_app_runs(slug: str, limit: int = 20) -> list[dict]:
    try:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT * FROM cron_runs
                   WHERE app_slug = %s
                   ORDER BY started_at DESC
                   LIMIT %s""",
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

        if not is_due(task["schedule"]):
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
