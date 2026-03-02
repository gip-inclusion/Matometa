# FastAPI Migration + Process Manager Extraction

> **Note (2026-03):** This plan predates the full PostgreSQL migration. SQLite references describe the architecture at the time of writing.

**Date:** 2026-02-21
**Status:** Ready for execution
**Builds on:** [2026-01-11-pubsub-streaming.md](2026-01-11-pubsub-streaming.md), [2026-01-10-architecture-audit.md](2026-01-10-architecture-audit.md)

---

## Why Both Changes Together

The two changes solve different problems but reinforce each other:

| Problem | FastAPI solves | PM extraction solves |
|---------|---------------|---------------------|
| Async/sync bridge complexity (`_get_async_loop`, `queue.Queue`, background thread) | Eliminates entirely — native async | N/A |
| Agent dies when web restarts | N/A | Agent survives in separate process |
| SSE streaming fragility | Native `StreamingResponse` with async generators | SSE becomes a DB/pubsub tail, no subprocess coupling |
| Can't add a second consumer (Matrix bridge, future webhook) | N/A | Any process can subscribe to events |
| `gunicorn --worker-class gevent` awkwardness | `uvicorn` with uvloop, no monkey-patching | N/A |
| `collect_events()` does 5 jobs at once | Async makes the flow linear, no queue hop | Splits persistence from delivery |

FastAPI first, PM extraction second. FastAPI makes the PM trivial to write (it's just an asyncio service). Doing PM first on Flask would mean rewriting the async bridge twice.

---

## What Stays The Same

- **Jinja2 templates** — FastAPI supports Jinja2 natively via `Jinja2Templates`. HTML structure unchanged.
- **SQLite/PostgreSQL storage** — No database changes. Same schema, same `store` module, same `database.py`.
- **Blueprint→Router structure** — Flask blueprints become FastAPI routers. 1:1 mapping.
- **AGENTS.md, skills, knowledge** — Untouched.
- **Docker setup** — Same container, different entrypoint command.
- **OAuth2-proxy auth** — Same `X-Forwarded-Email` header, extracted via FastAPI dependency.
- **Agent backends** — `CLIBackend`, `CLIOllamaBackend`, `AgentMessage` all unchanged.

---

## Phase 1: FastAPI Migration

### 1.1 New Dependencies

```diff
# requirements.txt
- Flask==3.1.2
- Werkzeug==3.1.4
- gunicorn==23.0.0
- gevent==24.11.1
+ fastapi==0.115.0
+ uvicorn[standard]==0.32.0
+ sse-starlette==2.2.1
+ python-multipart==0.0.17
```

Keep `Jinja2`, `markupsafe` (already dependencies). `python-multipart` is required by FastAPI for form/file uploads. Keep everything else unchanged.

### 1.2 Flask→FastAPI Pattern Reference

Every Flask-specific pattern in the codebase and its FastAPI equivalent:

| Flask pattern | Count | FastAPI equivalent |
|---------------|-------|--------------------|
| `Blueprint("name", __name__)` | 10 | `APIRouter()` |
| `@bp.route("/path", methods=["GET"])` | ~50 | `@router.get("/path")` |
| `request.get_json()` | 13 | Pydantic model or `dict` parameter with `Body()` |
| `request.args.get("key", default)` | ~25 | `key: type = Query(default)` function parameter |
| `request.args.getlist("key")` | 4 | `key: list[str] = Query([])` function parameter |
| `request.files["file"]` | 2 | `file: UploadFile` function parameter |
| `request.headers.get("X-...")` | 2 | `request: Request` then `request.headers.get()`, or dependency |
| `g.user_email` | 7 | `user: str = Depends(get_current_user)` |
| `jsonify(data)` | ~30 | Return `dict` directly |
| `render_template("x.html", **data)` | 13 | `templates.TemplateResponse(request, "x.html", {**data})` |
| `abort(404)` | 8 | `raise HTTPException(status_code=404)` |
| `redirect("/path", code=301)` | 8 | `RedirectResponse("/path", status_code=301)` |
| `url_for("blueprint.view")` | 1 | `request.url_for("view_name")` or hardcode path |
| `url_for("static", filename="x")` | 4 | `/static/x` (hardcoded, stable paths) |
| `Response(data, mimetype="...")` | 6 | `Response(data, media_type="...")` |
| `send_from_directory(dir, file)` | 2 | `StaticFiles` mount or `FileResponse` |
| `@app.template_filter("name")` | 2 | `templates.env.filters["name"] = func` |
| `@app.before_request` | 1 | Middleware class or per-route dependency |

**Not used** (no migration needed): `flash()`, `get_flashed_messages()`, `session`, Flask-WTF, Flask-Login.

### 1.3 Sync vs Async Handler Strategy

The storage layer (`database.py`, 2019 lines) uses `psycopg2` (synchronous). This is a hard constraint — we are NOT migrating to async database drivers in this plan.

**Rule:** Use `def` (not `async def`) for all handlers that call `store.*` methods. FastAPI automatically runs `def` handlers in a threadpool, so they won't block the event loop. Use `async def` only for:
- SSE streaming handlers (conversations, logs) where we need `async for`
- Handlers that do no I/O or only call async code

In `async def` handlers that must call sync `store.*` methods, use `asyncio.to_thread()`:
```python
messages = await asyncio.to_thread(store.get_messages, conv_id)
```

### 1.4 App Skeleton

```python
# web/app.py
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from . import config
from .routes import (
    conversations, reports, knowledge, html, query,
    cron, auth, research, rapports, logs,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.USES_CLAUDE_CLI:
        from . import claude_credentials
        claude_credentials.restore_credentials_from_s3()
    from . import sync_to_s3
    sync_to_s3.start_sync_watcher()
    yield

app = FastAPI(lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory="web/static"), name="static")
app.mount("/common", StaticFiles(directory=str(config.COMMON_DIR)), name="common")

# Interactive files — local or S3-backed
if not config.USE_S3:
    app.mount("/interactive", StaticFiles(directory=str(config.INTERACTIVE_DIR)), name="interactive")
# When USE_S3, /interactive/ routes handled by a dedicated handler (see html.py or app.py)

# Jinja2 templates with custom filters
templates = Jinja2Templates(directory="web/templates")
templates.env.filters["regex_replace"] = lambda v, p, r="": __import__("re").sub(p, r, str(v))
templates.env.filters["result_icon"] = result_icon_filter  # from current app.py

# Routers
app.include_router(html.router)
app.include_router(conversations.router, prefix="/api/conversations")
app.include_router(reports.router, prefix="/api/reports")
app.include_router(knowledge.router, prefix="/api/knowledge")
app.include_router(query.router, prefix="/api")
app.include_router(cron.router)
app.include_router(auth.router, prefix="/api/auth")
app.include_router(research.router)
app.include_router(rapports.router)
app.include_router(logs.router)
```

### 1.5 Auth Dependency (replaces `before_request` + `g`)

```python
# web/deps.py
from fastapi import Request
from . import config

def get_current_user(request: Request) -> str:
    """Extract authenticated user email from oauth2-proxy headers."""
    return request.headers.get("X-Forwarded-Email") or config.DEFAULT_USER

def get_current_user_name(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-User")
```

Usage in any route — explicit, testable, type-checked:
```python
@router.get("/{conv_id}")
def get_conversation(conv_id: str, user: str = Depends(get_current_user)):
    ...
```

### 1.6 Template Rendering

Templates need `request` in context. Create a shared helper:

```python
# web/deps.py (continued)
from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="web/templates")

def render(request: Request, template: str, **context):
    """Render a Jinja2 template with request context."""
    return templates.TemplateResponse(request, template, context)
```

Template `url_for()` for static files — replace with hardcoded paths:
```html
<!-- Before: {{ url_for('static', filename='css/style.css') }} -->
<!-- After:  /static/css/style.css -->
```

Only 4 template uses of `url_for` (all for static assets in `base.html`) plus 1 Python use in `rapports.py` (replace with `f"/rapports/{report_id}"`).

### 1.7 SSE Streaming (the big win)

Current Flask version (conversations.py ~lines 447-731) — 183 lines of sync/async bridging:

```python
# CURRENT: Flask
def generate():
    event_queue = queue.Queue()
    async def collect_events():
        async for event in agent.send_message(...):
            store_to_db(event)
            event_queue.put(("event", event))
        event_queue.put(("done", None))

    loop = _get_async_loop()  # background thread with persistent event loop
    future = asyncio.run_coroutine_threadsafe(collect_events(), loop)

    while True:
        msg_type, event = event_queue.get(timeout=120)
        if msg_type == "done":
            break
        yield f"event: {event.type}\ndata: {json.dumps(...)}\n\n"

return Response(generate(), mimetype="text/event-stream")
```

FastAPI version — direct async, no bridge:

```python
# NEW: FastAPI
from sse_starlette.sse import EventSourceResponse

@router.get("/{conv_id}/stream")
async def stream_conversation(conv_id: str):
    async def generate():
        async for event in agent.send_message(...):
            await asyncio.to_thread(store_to_db, event)
            yield {"event": event.type, "data": json.dumps(event.to_dict())}
        yield {"event": "done", "data": json.dumps({"conversation_id": conv_id})}

    return EventSourceResponse(generate())
```

The `_get_async_loop()`, `_loop_lock`, `_async_thread`, `queue.Queue()`, `run_coroutine_threadsafe()`, `future.result(timeout=5)` — all gone. ~80 lines of the most dangerous code in the project deleted.

**Important:** `store_to_db` calls are synchronous. Wrap in `asyncio.to_thread()` inside the `async def generate()` to avoid blocking the event loop.

### 1.8 Test Migration Strategy

The test suite (3,600+ lines) uses Flask's test client. FastAPI's `TestClient` (from Starlette, backed by `httpx`) has a nearly identical interface:

| Flask test pattern | FastAPI test pattern |
|--------------------|---------------------|
| `app.test_client()` | `TestClient(app)` |
| `response.get_json()` | `response.json()` |
| `response.data` | `response.content` |
| `response.status_code` | `response.status_code` (same) |
| `headers={...}` | `headers={...}` (same) |
| `app.test_request_context()` | Not needed — call `store.*` directly |

**Strategy:** Migrate tests alongside each route file. For each step:
1. Migrate the route file (Flask blueprint → FastAPI router)
2. Update the corresponding test file (Flask client → FastAPI TestClient)
3. Run tests, verify they pass
4. Commit

The `conftest.py` fixture changes once (Step 1):
```python
# tests/conftest.py
from fastapi.testclient import TestClient
from web.app import app

@pytest.fixture
def client(app):
    return TestClient(app)
```

SSE streaming tests (`test_sse_streaming.py`, 525 lines) migrate last alongside `conversations.py`. The mock agent backend pattern (`_make_mock_backend`) stays identical — it's framework-agnostic.

### 1.9 Route-by-Route Migration

Complete inventory of all 10 route files, ordered by risk:

| # | File | Lines | Templates | Streaming | Agent | Tests |
|---|------|-------|-----------|-----------|-------|-------|
| 1 | `query.py` | 104 | No | No | No | None |
| 2 | `logs.py` | 58 | No | SSE (simple) | No | None |
| 3 | `auth.py` | 100 | No | No | No | None |
| 4 | `cron.py` | 76 | Yes (1) | No | No | None |
| 5 | `knowledge.py` | 222 | No | No | No | None |
| 6 | `reports.py` | 232 | No | No | No | None |
| 7 | `rapports.py` | 223 | Yes (1) | No | No | None |
| 8 | `research.py` | 631 | Yes (1) | No | No | None |
| 9 | `html.py` | 620 | Yes (9) | No | No | `test_shared_conversations.py` |
| 10 | `conversations.py` | 921 | No | SSE (complex) | Yes | `test_sse_streaming.py`, `test_fork_conversation.py`, `test_uploads.py`, `test_token_tracking.py`, `test_api_signals.py` |

**Notes:**
- `research.py` uses `sentence-transformers` for CPU-intensive embedding computation. Keep these handlers as `def` so they run in the threadpool without blocking the event loop.
- `logs.py` has a simple SSE handler for log streaming — good warm-up for the complex one in `conversations.py`.
- `html.py` is the most template-heavy file (9 render_template calls). Mechanical but needs visual verification.

### 1.10 Procfile / Dockerfile Changes

```diff
# Procfile
- web: gunicorn --worker-class gevent --workers 2 --bind 0.0.0.0:$PORT web.app:app
+ web: uvicorn web.app:app --host 0.0.0.0 --port $PORT --workers 2
```

```diff
# Dockerfile (entrypoint)
- CMD ["python", "-m", "web.app"]
+ CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "5000"]
```

For local development:
```bash
uvicorn web.app:app --reload --host 127.0.0.1 --port 5000
```

The `--reload` flag gives hot reload without gevent monkey-patching.

---

## Phase 1 Execution Plan

### Step 1: Infrastructure — app skeleton, deps, test setup

- Update `requirements.txt` (add FastAPI/uvicorn/sse-starlette/python-multipart, remove Flask/gunicorn/gevent)
- Create `web/deps.py` with `get_current_user`, `get_current_user_name`, `templates`, `render` helper
- Rewrite `web/app.py` as FastAPI app with lifespan, static mounts, Jinja2 filters
- Update `tests/conftest.py` to use `TestClient(app)` instead of `app.test_client()`
- Port `query.py` as proof of concept (simplest route, pure JSON API)
- Run existing tests that don't depend on specific routes
- **Gate:** `pytest` passes for non-route-specific tests. Query endpoint returns correct JSON via `TestClient`.

### Step 2: Port simple JSON API routes

Port in order, each with its test updates:
1. `auth.py` (100 lines) — tests the `get_current_user` dependency
2. `logs.py` (58 lines) — includes a simple SSE handler, good practice
3. `cron.py` (76 lines) — first template route, tests Jinja2 integration
4. `knowledge.py` (222 lines) — uses `g.user_email`, tests dependency injection
5. `reports.py` (232 lines) — medium CRUD, uses `g.user_email`

- **Gate:** all 5 route files ported. `pytest` passes. JSON APIs return correct data. Cron page renders.

### Step 3: Port template-heavy and complex routes

1. `rapports.py` (223 lines) — templates + `url_for` + `Markup` + S3 scanning
2. `research.py` (631 lines) — large, CPU-intensive embeddings, keep as `def` handlers
3. `html.py` (620 lines) — 9 templates, most `request.args` usage, redirects

- **Gate:** all pages render correctly. Visual check of each template. `pytest` passes including `test_shared_conversations.py`.

### Step 4: Port conversations + streaming

- Port `conversations.py` (921 lines) with native async SSE via `sse-starlette`
- Delete `_get_async_loop`, `_loop_lock`, `_async_thread`, `queue.Queue` bridge (~80 lines)
- Wrap sync `store.*` calls in `asyncio.to_thread()` inside async generators
- File upload: `request.files["file"]` → `UploadFile` parameter
- Update all conversation tests: `test_sse_streaming.py`, `test_fork_conversation.py`, `test_uploads.py`, `test_token_tracking.py`, `test_api_signals.py`
- **Gate:** full conversation flow works end-to-end. All tests pass. SSE stream delivers events correctly. File uploads work.

### Step 5: Cut over and cleanup

- Update Procfile: `gunicorn` → `uvicorn`
- Update Dockerfile CMD
- Update `web/__main__.py` (if it exists) for `python -m web.app` entrypoint
- Remove Flask, Werkzeug, gunicorn, gevent from requirements
- Search for any remaining Flask imports, remove them
- Full `pytest` run
- **Gate:** all tests pass. Application starts with uvicorn. No Flask imports remain.

---

## Phase 2: Process Manager Extraction (deferred)

### 2.1 What the PM Does

The PM is a small asyncio service that owns Claude CLI subprocesses. It does exactly what `CLIBackend` + the persistence half of `collect_events()` do today, but in its own process.

Responsibilities:
- Spawn `claude` subprocess with correct args
- Parse stream-json stdout line by line
- Write each event to the database (messages, session_id, usage)
- Track running processes (for cancel, status)
- Handle SIGTERM → SIGKILL lifecycle on cancel
- Set `needs_response=True` when starting, `False` when done

What it does NOT do:
- SSE formatting
- Tool taxonomy classification (move to web layer or do on read)
- Audit logging (move to web layer)
- Title/tag generation (stays in web layer, triggered after PM reports completion)

### 2.2 Communication: Database, Not Unix Sockets

The PM and web process communicate through the database. No Unix socket API, no `aiohttp` dependency. The database is already shared — use it as the coordination layer.

**PM → Web (event delivery):** PM writes events to the `messages` table. Web process tails the table (polling for SQLite, LISTEN/NOTIFY for PostgreSQL).

**Web → PM (commands):** Web process writes a row to a `pm_commands` table (or updates a `conversations` field). PM polls for pending commands.

```sql
-- New: lightweight command queue
CREATE TABLE pm_commands (
    id INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    command TEXT NOT NULL,  -- 'run' or 'cancel'
    payload JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);
```

This eliminates:
- The `aiohttp` dependency
- Unix socket setup and permissions
- The 4-endpoint REST API
- Connection management between processes

The PM becomes a simple loop: poll for unprocessed commands, execute them, mark as processed.

### 2.3 Storage Layer Additions

New methods needed in `database.py`:

```python
def get_messages_since(self, conversation_id: str, after_id: int) -> list[Message]:
    """Get messages with id > after_id for a conversation."""

def enqueue_pm_command(self, conversation_id: str, command: str, payload: dict):
    """Queue a command for the process manager."""

def get_pending_pm_commands(self) -> list[dict]:
    """Get unprocessed PM commands."""

def mark_pm_command_processed(self, command_id: int):
    """Mark a PM command as processed."""
```

### 2.4 PM Implementation

```python
# web/pm.py  (~150 lines, no web framework needed)

import asyncio
from .agents.cli import CLIBackend
from .storage import store

class ProcessManager:
    def __init__(self):
        self.backend = CLIBackend()
        self.running: dict[str, asyncio.Task] = {}

    async def run(self):
        """Main loop: poll for commands, execute them."""
        while True:
            commands = await asyncio.to_thread(store.get_pending_pm_commands)
            for cmd in commands:
                if cmd["command"] == "run":
                    task = asyncio.create_task(
                        self._run_agent(cmd["conversation_id"], cmd["payload"])
                    )
                    self.running[cmd["conversation_id"]] = task
                elif cmd["command"] == "cancel":
                    await self._cancel_agent(cmd["conversation_id"])
                await asyncio.to_thread(store.mark_pm_command_processed, cmd["id"])
            await asyncio.sleep(0.5)

    async def _run_agent(self, conversation_id, payload):
        """Run agent, write events to DB."""
        try:
            async for event in self.backend.send_message(
                conversation_id, payload["prompt"],
                payload["history"], payload.get("session_id"),
            ):
                await asyncio.to_thread(self._persist_event, conversation_id, event)
        finally:
            await asyncio.to_thread(
                store.update_conversation, conversation_id, needs_response=False
            )
            self.running.pop(conversation_id, None)
```

### 2.5 Web Process Changes

After PM extraction, the SSE handler in `conversations.py` becomes a DB tail:

```python
@router.get("/{conv_id}/stream")
async def stream_conversation(conv_id: str):
    async def generate():
        last_msg_id = 0
        while True:
            new_messages = await asyncio.to_thread(
                store.get_messages_since, conv_id, last_msg_id
            )
            for msg in new_messages:
                last_msg_id = msg.id
                yield {"event": msg.type, "data": json.dumps(msg.to_dict())}

            conv = await asyncio.to_thread(store.get_conversation, conv_id)
            if not conv.needs_response:
                yield {"event": "done", "data": json.dumps({"conversation_id": conv_id})}
                return

            await asyncio.sleep(0.3)

    return EventSourceResponse(generate())
```

### 2.6 PostgreSQL LISTEN/NOTIFY (replaces polling)

When running PostgreSQL (production), replace the 300ms poll with push:

```python
# PM: after storing an event
await conn.execute(f"NOTIFY conv_{conversation_id}, '{msg_id}'")

# Web: SSE handler
async def generate():
    async for notification in listen(f"conv_{conv_id}"):
        msg = await asyncio.to_thread(store.get_message, notification.payload)
        yield {"event": msg.type, "data": json.dumps(msg.to_dict())}
```

Zero latency, zero wasted queries. SQLite falls back to polling.

### 2.7 Running the PM

```
# Procfile
web: uvicorn web.app:app --host 0.0.0.0 --port $PORT --workers 2
pm:  python -m web.pm
```

Docker: use a simple shell entrypoint:
```bash
#!/bin/sh
python -m web.pm &
PM_PID=$!
trap "kill $PM_PID" EXIT
exec uvicorn web.app:app --host 0.0.0.0 --port $PORT --workers 2
```

### 2.8 Lifecycle Safety

**Crash recovery:** If the PM crashes mid-conversation, the conversation is stuck with `needs_response=True`. On PM startup, scan for conversations with `needs_response=True` and no running process — mark them as errored or retry.

**Heartbeat:** PM updates a `pm_heartbeat` timestamp every 10s. Web process checks this to show "agent offline" status if the PM is down.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Jinja2 template subtleties between Flask and FastAPI | Broken pages | Port one template at a time, visual diff. `url_for` only used 5 times (all static assets — hardcode paths). |
| `gevent` monkey-patching removal breaks something | Runtime errors | gevent is only used for gunicorn workers; app code doesn't use gevent APIs directly. |
| `sse-starlette` behavior differs from hand-rolled SSE | Stream drops | Test with slow connections, client disconnect, browser refresh. |
| Sync `store.*` calls in `async def` handlers block event loop | Performance degradation | Use `def` handlers by default. Use `asyncio.to_thread()` in async generators. |
| Test migration misses edge cases | Silent regressions | Migrate tests alongside each route file. Run full suite after each step. |
| `TestClient` vs Flask test client subtle differences | Test failures | `response.get_json()` → `.json()`, `response.data` → `.content`. Mechanical changes. |
| CPU-intensive `research.py` (sentence-transformers) blocks event loop | Slow responses | Keep research handlers as `def` (threadpool). Do not use `async def`. |
| PM SQLite concurrent writes (Phase 2) | Database locked | Already using WAL mode. PM is primary writer, web mostly reads. Add retry with backoff if needed. |
| PM crash leaves conversations stuck (Phase 2) | Orphaned `needs_response=True` | Crash recovery scan on PM startup. Heartbeat monitoring. |

---

## What This Enables

After Phase 1 (FastAPI):
1. **Native async** — no more sync/async bridge for SSE streaming
2. **Hot reload** — `uvicorn --reload` without gevent monkey-patching
3. **Simpler test infrastructure** — `TestClient` with httpx, no Flask request context
4. **Type-checked dependencies** — `Depends()` instead of `g.user_email`
5. **Foundation for PM** — async handlers make the PM extraction trivial

After Phase 2 (PM extraction):
1. **Agent survives web restart** — PM runs independently
2. **Multiple consumers** — Matrix bridge, webhooks subscribe via DB/NOTIFY
3. **Horizontal scaling** — stateless web workers, single PM
4. **Cleaner testing** — test SSE by inserting DB rows, test PM by mocking CLIBackend

---

## Appendix: Lines of Code Impact

| File | Current LOC | After FastAPI | After PM |
|------|-------------|---------------|----------|
| `conversations.py` | 921 | ~800 (no async bridge) | ~500 (no agent logic) |
| `app.py` | 194 | ~80 (lifespan + mounts + filters) | ~80 |
| `agents/cli.py` | 340 | 340 (unchanged) | 340 (moved to PM) |
| `html.py` | 620 | ~630 (minimal changes) | ~630 |
| **New: `deps.py`** | — | ~25 | ~25 |
| **New: `pm.py`** | — | — | ~200 |
| **Deleted:** `_get_async_loop` + queue bridge | ~80 | 0 | 0 |
| **Tests adapted** | 3,600+ | ~3,600 (same count, different client) | ~3,600 |

Net Phase 1: ~100 fewer lines, dramatically simpler control flow in the streaming path.
Net Phase 2: +200 (pm.py), −250 (conversations.py agent logic). Cleaner separation.
