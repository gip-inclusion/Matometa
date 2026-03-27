"""Self-test route: lightweight health checks for all core services."""

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass
from functools import partial
from typing import Callable

import requests
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from lib._sources import get_source_config, list_instances
from lib.query import get_matomo

from . import config, s3
from .database import store
from .db import get_db

__all__ = ["router", "Check"]

SELFTEST_TIMEOUT_SEC = 3

router = APIRouter()


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    duration_ms: int = 0


def probe(name: str, fn: Callable[[], tuple[bool, str]]) -> Check:
    t0 = time.monotonic()
    try:
        ok, detail = fn()
        return Check(name, ok, detail, int((time.monotonic() - t0) * 1000))
    except Exception as exc:
        return Check(name, False, str(exc)[:120], int((time.monotonic() - t0) * 1000))


def format_check_line(check: Check) -> str:
    icon = "\u2705" if check.ok else "\u274c"
    line = f"{icon} {check.name}"
    if check.detail:
        line += f"  \u2014  {check.detail}"
    if check.duration_ms:
        line += f"  ({check.duration_ms}ms)"
    return line


def check_postgresql() -> tuple[bool, str]:
    with get_db() as conn:
        row = conn.execute("SELECT 1 AS ok").fetchone()
    return (bool(row and row["ok"] == 1), "")


def check_admin_users() -> tuple[bool, str]:
    n = len(config.ADMIN_USERS)
    if not n:
        return (False, "ADMIN_USERS is empty")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM conversations WHERE user_id IN %s LIMIT 1",
            (tuple(config.ADMIN_USERS),),
        ).fetchall()
    if rows:
        return (True, f"{n} configured, at least 1 active")
    return (True, f"{n} configured (none active yet)")


def check_process_manager() -> tuple[bool, str]:
    alive = store.is_pm_alive(max_age_seconds=30)
    return (alive, "heartbeat OK" if alive else "no recent heartbeat")


def check_conversation_roundtrip() -> tuple[bool, str]:
    conv = store.create_conversation(user_id="selftest@localhost")
    store.add_message(conv.id, "user", "selftest ping")
    msgs = store.get_messages(conv.id)
    ok = len(msgs) >= 1
    with get_db() as conn:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = %s",
            (conv.id,),
        )
        conn.execute(
            "DELETE FROM conversations WHERE id = %s",
            (conv.id,),
        )
    return (ok, "create/write/read/delete OK")


def check_claude_cli() -> tuple[bool, str]:
    """`claude --version` from repo root + one folder name per `skills/<name>/SKILL.md`."""
    result = subprocess.run(
        [config.CLAUDE_CLI, "--version"],
        cwd=str(config.BASE_DIR),
        capture_output=True,
        text=True,
        timeout=SELFTEST_TIMEOUT_SEC,
    )
    if result.returncode != 0:
        return (False, (result.stderr or result.stdout).strip()[:120])
    cli_line = result.stdout.strip().split("\n")[0][:80]

    skills_root = config.BASE_DIR / "skills"
    if not skills_root.is_dir():
        return (False, f"{cli_line}; skills/ missing")
    names = sorted(p.name for p in skills_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
    if not names:
        return (False, f"{cli_line}; no skills/*/SKILL.md")

    tail = ", ".join(names)
    if len(tail) > 90:
        tail = tail[:87] + "..."
    return (True, f"{cli_line}; {len(names)} skills: {tail}")


def check_s3() -> tuple[bool, str]:
    if not config.USE_S3:
        return (False, "not configured (USE_S3=false)")
    filename = "apps-list.json"
    if not s3.file_exists(filename):
        return (False, f"object not found: {filename}")
    return (True, f"bucket={config.S3_BUCKET} object {filename}")


def check_matomo() -> tuple[bool, str]:
    api = get_matomo("inclusion")
    resp = requests.get(
        f"https://{api.url}/index.php",
        params={
            "module": "API",
            "method": "API.getMatomoVersion",
            "format": "json",
            "token_auth": api.token,
        },
        timeout=SELFTEST_TIMEOUT_SEC,
    )
    resp.raise_for_status()
    version = resp.json().get("value", "?")[:40]
    return (True, f"v{version}")


def check_metabase_instance(instance: str) -> tuple[bool, str]:
    cfg = get_source_config("metabase", instance)
    url = cfg["url"].rstrip("/") + "/api/health"
    resp = requests.get(url, timeout=SELFTEST_TIMEOUT_SEC)
    if resp.status_code == 200:
        return (True, "healthy")
    return (False, f"HTTP {resp.status_code}")


def check_notion() -> tuple[bool, str]:
    token = os.getenv("NOTION_TOKEN")
    if not token:
        return (False, "NOTION_TOKEN not set")
    resp = requests.get(
        "https://api.notion.com/v1/users/me",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
        },
        timeout=SELFTEST_TIMEOUT_SEC,
    )
    if resp.status_code == 200:
        return (True, f"bot: {resp.json().get('name', 'ok')}")
    return (False, f"HTTP {resp.status_code}")


def check_grist() -> tuple[bool, str]:
    api_key = os.getenv("GRIST_API_KEY")
    doc_id = os.getenv("GRIST_WEBINAIRES_DOC_ID")
    if not api_key or not doc_id:
        return (False, "GRIST_API_KEY or DOC_ID not set")
    resp = requests.get(
        f"https://grist.numerique.gouv.fr/api/docs/{doc_id}/tables",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=SELFTEST_TIMEOUT_SEC,
    )
    if resp.status_code == 200:
        n = len(resp.json().get("tables", []))
        return (True, f"{n} tables")
    return (False, f"HTTP {resp.status_code}")


def check_livestorm() -> tuple[bool, str]:
    api_key = os.getenv("LIVESTORM_API_KEY")
    if not api_key:
        return (False, "LIVESTORM_API_KEY not set")
    resp = requests.get(
        "https://api.livestorm.co/v1/ping",
        headers={"Authorization": api_key},
        timeout=SELFTEST_TIMEOUT_SEC,
    )
    if resp.status_code == 200:
        return (True, "reachable")
    return (False, f"HTTP {resp.status_code}")


def check_slack() -> tuple[bool, str]:
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        return (False, "SLACK_BOT_TOKEN not set")
    resp = requests.head(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {token}"},
        timeout=SELFTEST_TIMEOUT_SEC,
    )
    if resp.status_code == 200:
        return (True, "API reachable")
    return (False, f"HTTP {resp.status_code}")


def run_selftest_checks() -> list[Check]:
    checks = [
        probe("PostgreSQL", check_postgresql),
        probe("Admin users", check_admin_users),
        probe("Process Manager", check_process_manager),
        probe("Conversation roundtrip", check_conversation_roundtrip),
        probe("Claude CLI", check_claude_cli),
        probe("S3", check_s3),
        probe("Matomo", check_matomo),
    ]
    for inst in list_instances("metabase"):
        checks.append(
            probe(
                f"Metabase ({inst})",
                partial(check_metabase_instance, inst),
            )
        )
    checks += [
        probe("Notion", check_notion),
        probe("Grist", check_grist),
        probe("Livestorm", check_livestorm),
        probe("Slack", check_slack),
    ]
    return checks


@router.get("/selftest")
async def selftest():
    checks = await asyncio.to_thread(run_selftest_checks)
    total = len(checks)
    passed = sum(1 for c in checks if c.ok)
    failed = total - passed

    header = f"Autometa selftest  —  {passed}/{total} OK"
    if failed:
        header += f"  ({failed} failed)"
    lines = [header, ""]
    lines.extend(format_check_line(c) for c in checks)
    lines.append("")

    status = 200 if failed == 0 else 503
    return PlainTextResponse("\n".join(lines), status_code=status)
