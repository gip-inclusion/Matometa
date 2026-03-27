"""Route GET /selftest : checks services ; HTML consomme le flux text/plain par SNAPSHOT_SEP."""

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from lib._sources import list_instances

from . import config

router = APIRouter()

SNAPSHOT_SEP = "\n---\n"


def _first_accept(accept: str) -> str:
    if not accept or not accept.strip():
        return "*/*"
    return accept.split(",")[0].strip().split(";")[0].strip().lower()


def _selftest_page_html() -> str:
    sep = json.dumps(SNAPSHOT_SEP)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Autometa selftest</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1rem; }}
pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; }}
</style>
</head>
<body>
<pre id="out">Chargement…</pre>
<script>
(async () => {{
  const SEP = {sep};
  const pre = document.getElementById("out");
  const r = await fetch("/selftest", {{ headers: {{ Accept: "text/plain" }} }});
  if (!r.ok) {{ pre.textContent = "HTTP " + r.status; return; }}
  const dec = new TextDecoder();
  const reader = r.body.getReader();
  let buf = "";
  while (true) {{
    const {{ done, value }} = await reader.read();
    if (value) buf += dec.decode(value, {{ stream: true }});
    const parts = buf.split(SEP);
    buf = parts.pop() ?? "";
    for (const p of parts) {{
      const t = p.replace(/^\\n+|\\n+$/g, "");
      if (t) pre.textContent = t;
    }}
    if (done) break;
  }}
  const tail = buf.replace(/^\\n+|\\n+$/g, "");
  if (tail) pre.textContent = tail;
}})();
</script>
</body>
</html>"""


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
        # Why: un check isolé ne doit pas faire échouer les autres.
        return Check(name, False, str(exc)[:120], int((time.monotonic() - t0) * 1000))


def _fmt(check: Check) -> str:
    icon = "\u2705" if check.ok else "\u274c"
    line = f"{icon} {check.name}"
    if check.detail:
        line += f"  \u2014  {check.detail}"
    if check.duration_ms:
        line += f"  ({check.duration_ms}ms)"
    return line


def _fmt_pending(name: str) -> str:
    return f"[PENDING]  {name}"


def _render_snapshot(names: list[str], results: list[Check | None]) -> str:
    total = len(names)
    done = [c for c in results if c is not None]
    passed = sum(1 for c in done if c.ok)
    failed = sum(1 for c in done if not c.ok)
    pending_n = sum(1 for c in results if c is None)

    header = f"Autometa selftest  —  {passed}/{total} OK"
    if pending_n:
        header += f"  ({pending_n} pending)"
    elif failed:
        header += f"  ({failed} failed)"

    lines = [header, ""]
    for i, name in enumerate(names):
        c = results[i]
        lines.append(_fmt(c) if c is not None else _fmt_pending(name))
    lines.append("")
    return "\n".join(lines)


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
    from .database import store

    alive = store.is_pm_alive(max_age_seconds=30)
    return (alive, "heartbeat OK" if alive else "no recent heartbeat")


def _check_conversation_roundtrip() -> tuple[bool, str]:
    from .database import store
    from .db import get_db

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


def _check_claude_status_page() -> tuple[bool, str]:
    url = "https://status.claude.com/api/v2/summary.json"
    resp = requests.get(url, timeout=5, headers={"Accept": "application/json"})
    if resp.status_code != 200:
        return (False, f"HTTP {resp.status_code}")
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return (False, "invalid JSON")
    status = data.get("status") or {}
    indicator = status.get("indicator") or ""
    description = (status.get("description") or "").strip() or indicator or "unknown"
    components = data.get("components") or []
    non_op = [c["name"] for c in components if c.get("status") != "operational"]
    if indicator == "none" and not non_op:
        return (True, description)
    extra = ", ".join(non_op[:8])
    if len(non_op) > 8:
        extra += f", +{len(non_op) - 8} more"
    msg = f"{description} ({extra})" if extra else description
    return (False, msg[:240])


def _check_claude_code_ping() -> tuple[bool, str]:
    result = subprocess.run(
        [
            config.CLAUDE_CLI,
            "--print",
            "-p",
            "Reply with exactly the single word: pong",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(config.BASE_DIR),
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()[:120]
        return (False, err or "non-zero exit")
    if "pong" in result.stdout.lower():
        return (True, "API OK")
    return (False, "no pong in output")


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


def _check_specs() -> list[tuple[str, Callable[[], tuple[bool, str]]]]:
    specs: list[tuple[str, Callable[[], tuple[bool, str]]]] = [
        ("PostgreSQL", _check_postgresql),
        ("Admin users", _check_admin_users),
        ("Process Manager", _check_process_manager),
        ("Conversation roundtrip", _check_conversation_roundtrip),
        ("Claude CLI", _check_claude_cli),
        ("Claude status page", _check_claude_status_page),
        ("Claude Code API ping", _check_claude_code_ping),
        ("S3", _check_s3),
        ("Matomo", _check_matomo),
    ]
    for inst in list_instances("metabase"):
        specs.append((f"Metabase ({inst})", lambda i=inst: _check_metabase_instance(i)))
    specs += [
        ("Notion", _check_notion),
        ("Grist", _check_grist),
        ("Livestorm", _check_livestorm),
        ("Slack", _check_slack),
    ]
    return specs


def _run_all_checks() -> list[Check]:
    return [_probe(name, fn) for name, fn in _check_specs()]


async def _run_checks_streaming():
    specs = _check_specs()
    names = [n for n, _ in specs]
    results: list[Check | None] = [None] * len(names)

    async def one(i: int, name: str, fn: Callable[[], tuple[bool, str]]) -> tuple[int, Check]:
        return i, await asyncio.to_thread(_probe, name, fn)

    pending = {asyncio.create_task(one(i, name, fn)) for i, (name, fn) in enumerate(specs)}

    yield _render_snapshot(names, results)

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            idx, check = task.result()
            results[idx] = check
            yield _render_snapshot(names, results)


@router.get("/selftest")
async def selftest(request: Request):
    if _first_accept(request.headers.get("accept", "")) == "text/html":
        return HTMLResponse(_selftest_page_html())

    async def body():
        async for chunk in _run_checks_streaming():
            yield chunk + SNAPSHOT_SEP

    return StreamingResponse(body(), media_type="text/plain; charset=utf-8")
