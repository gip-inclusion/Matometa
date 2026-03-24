"""Self-test route: lightweight health checks for all core services."""

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

import requests
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from lib._sources import list_instances

from . import config

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    duration_ms: int = 0


def _probe(name: str, fn: Callable[[], tuple[bool, str]]) -> Check:
    t0 = time.monotonic()
    try:
        ok, detail = fn()
        return Check(name, ok, detail, int((time.monotonic() - t0) * 1000))
    except Exception as exc:
        return Check(name, False, str(exc)[:120], int((time.monotonic() - t0) * 1000))


def _fmt(check: Check) -> str:
    icon = "\u2705" if check.ok else "\u274c"
    line = f"{icon} {check.name}"
    if check.detail:
        line += f"  \u2014  {check.detail}"
    if check.duration_ms:
        line += f"  ({check.duration_ms}ms)"
    return line


def _check_postgresql() -> tuple[bool, str]:
    from .db import get_db

    with get_db() as conn:
        row = conn.execute("SELECT 1 AS ok").fetchone()
    return (bool(row and row["ok"] == 1), "")


def _check_admin_users() -> tuple[bool, str]:
    n = len(config.ADMIN_USERS)
    if not n:
        return (False, "ADMIN_USERS is empty")
    from .db import get_db

    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM conversations WHERE user_id IN %s LIMIT 1",
            (tuple(config.ADMIN_USERS),),
        ).fetchall()
    if rows:
        return (True, f"{n} configured, at least 1 active")
    return (True, f"{n} configured (none active yet)")


def _check_process_manager() -> tuple[bool, str]:
    from .storage import store

    alive = store.is_pm_alive(max_age_seconds=30)
    return (alive, "heartbeat OK" if alive else "no recent heartbeat")


def _check_conversation_roundtrip() -> tuple[bool, str]:
    from .db import get_db
    from .storage import store

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


def _check_claude_cli() -> tuple[bool, str]:
    result = subprocess.run(
        [config.CLAUDE_CLI, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        return (True, result.stdout.strip().split("\n")[0][:80])
    return (False, result.stderr.strip()[:120])


def _check_s3() -> tuple[bool, str]:
    if not config.USE_S3:
        return (False, "not configured (USE_S3=false)")
    from . import s3

    s3._s3_client.head_bucket(Bucket=config.S3_BUCKET)
    return (True, f"bucket={config.S3_BUCKET}")


def _check_matomo() -> tuple[bool, str]:
    from lib.query import get_matomo

    api = get_matomo("inclusion")
    resp = requests.get(
        f"https://{api.url}/index.php",
        params={
            "module": "API",
            "method": "API.getMatomoVersion",
            "format": "json",
            "token_auth": api.token,
        },
        timeout=10,
    )
    resp.raise_for_status()
    version = resp.json().get("value", "?")[:40]
    return (True, f"v{version}")


def _check_metabase_instance(instance: str) -> tuple[bool, str]:
    from lib._sources import get_source_config

    cfg = get_source_config("metabase", instance)
    url = cfg["url"].rstrip("/") + "/api/health"
    resp = requests.get(url, timeout=10)
    if resp.status_code == 200:
        return (True, "healthy")
    return (False, f"HTTP {resp.status_code}")


def _check_notion() -> tuple[bool, str]:
    token = os.getenv("NOTION_TOKEN")
    if not token:
        return (False, "NOTION_TOKEN not set")
    resp = requests.get(
        "https://api.notion.com/v1/users/me",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
        },
        timeout=10,
    )
    if resp.status_code == 200:
        return (True, f"bot: {resp.json().get('name', 'ok')}")
    return (False, f"HTTP {resp.status_code}")


def _check_grist() -> tuple[bool, str]:
    api_key = os.getenv("GRIST_API_KEY")
    doc_id = os.getenv("GRIST_WEBINAIRES_DOC_ID")
    if not api_key or not doc_id:
        return (False, "GRIST_API_KEY or DOC_ID not set")
    resp = requests.get(
        f"https://grist.numerique.gouv.fr/api/docs/{doc_id}/tables",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code == 200:
        n = len(resp.json().get("tables", []))
        return (True, f"{n} tables")
    return (False, f"HTTP {resp.status_code}")


def _check_livestorm() -> tuple[bool, str]:
    api_key = os.getenv("LIVESTORM_API_KEY")
    if not api_key:
        return (False, "LIVESTORM_API_KEY not set")
    resp = requests.get(
        "https://api.livestorm.co/v1/ping",
        headers={"Authorization": api_key},
        timeout=10,
    )
    if resp.status_code == 200:
        return (True, "reachable")
    return (False, f"HTTP {resp.status_code}")


def _check_slack() -> tuple[bool, str]:
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        return (False, "SLACK_BOT_TOKEN not set")
    resp = requests.head(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code == 200:
        return (True, "API reachable")
    return (False, f"HTTP {resp.status_code}")


def _check_deepinfra() -> tuple[bool, str]:
    key = config.DEEPINFRA_API_KEY
    if not key:
        return (False, "DEEPINFRA_API_KEY not set")
    resp = requests.get(
        "https://api.deepinfra.com/v1/openai/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=10,
    )
    if resp.status_code == 200:
        return (True, "reachable")
    return (False, f"HTTP {resp.status_code}")


def _run_all_checks() -> list[Check]:
    checks = [
        _probe("PostgreSQL", _check_postgresql),
        _probe("Admin users", _check_admin_users),
        _probe("Process Manager", _check_process_manager),
        _probe("Conversation roundtrip", _check_conversation_roundtrip),
        _probe("Claude CLI", _check_claude_cli),
        _probe("S3", _check_s3),
        _probe("Matomo", _check_matomo),
    ]
    for inst in list_instances("metabase"):
        checks.append(
            _probe(
                f"Metabase ({inst})",
                lambda i=inst: _check_metabase_instance(i),
            )
        )
    checks += [
        _probe("Notion", _check_notion),
        _probe("Grist", _check_grist),
        _probe("Livestorm", _check_livestorm),
        _probe("Slack", _check_slack),
        _probe("DeepInfra (embeddings)", _check_deepinfra),
    ]
    return checks


@router.get("/selftest")
async def selftest():
    checks = await asyncio.to_thread(_run_all_checks)
    total = len(checks)
    passed = sum(1 for c in checks if c.ok)
    failed = total - passed

    header = f"Autometa selftest  —  {passed}/{total} OK"
    if failed:
        header += f"  ({failed} failed)"
    lines = [header, ""]
    lines.extend(_fmt(c) for c in checks)
    lines.append("")

    status = 200 if failed == 0 else 503
    return PlainTextResponse("\n".join(lines), status_code=status)
