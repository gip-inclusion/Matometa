# Scaling & Performance Recommendations

Status: living document. Items marked **DONE** are implemented.

---

## 1. Faster Deploys

### 1.1 uv on Scalingo — **DONE** (already in place)

Scalingo's Python buildpack already detects `pyproject.toml` + `uv.lock` and uses uv.
Build logs confirm: `Using cached uv 0.10.1` / `Installing dependencies using 'uv sync'`.

The old `web/requirements.txt` (Flask, claude-agent-sdk) is stale and unused. Can be deleted.

### 1.2 Cache Claude CLI binary — **DONE**

`bin/post_compile` caches the Claude Code binary in `$CACHE_DIR` between deploys.

### 1.3 Reduce deploy frequency

The GitHub Actions workflow deploys on every push to main. Consider batching changes
or deploying only on tags/releases if deploy downtime becomes an issue.

---

## 2. More Concurrent Chats

### 2.1 WEB_CONCURRENCY=1 — **DONE**

Async uvicorn doesn't benefit from multiple workers. Set to 1, saves ~100MB RAM
= room for one more CLI process. Applied via `scalingo env-set`.

### 2.2 Concurrent agent limit — **DONE**

Process manager now caps concurrent CLI processes at `MAX_CONCURRENT_AGENTS` (default 2).
Extra requests are queued and start automatically when a slot opens.
Configurable via env var.

### 2.3 Session retry on crash — **DONE**

CLI now retries without `--resume` when it exits with no useful output.
Fixes corrupted sessions that previously caused permanent stuck conversations.

### 2.4 Separate PM into its own worker dyno

**Status**: under consideration.

The process manager currently runs in-process with uvicorn. Moving it to a separate
`worker` dyno would allow independent scaling:

```
web: start_with_oauth2_proxy.sh uvicorn web.app:app --host 0.0.0.0 --port 8080
worker: python -m web.pm
```

**For:**
- Scale agents independently of web serving (2 worker dynos = 4 concurrent agents)
- Web container stays lean, lower memory, faster restarts
- Agent crash doesn't take down the web server
- Scalingo supports worker dynos natively

**Against:**
- Two containers = double the base cost
- Both need the full Python dependency set (pandas, scikit-learn, etc.) because
  the agent imports tools that use these. Can't easily split dependencies without
  a major refactor to externalize tool code.
- Operational complexity: monitoring two processes, coordinating deploys
- The PM is lightweight Python — it's the CLI subprocesses that use memory,
  and those would exist regardless of where the PM runs

**Sideways: dedicated agent container with minimal deps**

The real memory hog is the Claude CLI (Node.js, ~200MB per process), not Python.
A truly lean worker would need:
1. Node.js + Claude CLI binary
2. Minimal Python for the PM loop + DB access
3. None of the data science stack

This would require the agent tools (Matomo queries, Metabase queries, etc.) to be
exposed as HTTP endpoints or MCP servers that the CLI calls remotely, rather than
being local Python scripts. This is a significant architectural change but would
make the worker container ~50MB instead of ~500MB.

**Recommendation**: stay in-process for now. The Large container (1GB) supports
2 concurrent agents comfortably. If you need 4+, separate the worker first
as-is (accepting the duplicate deps), then optimize the image later.

### 2.5 Agent SDK vs CLI — measured, no difference

Spike results (local, single "reply SPIKE_OK" prompt):

| | CLI (current) | Agent SDK |
|---|---|---|
| Memory (children RSS) | **316 MB** | **299 MB** |
| Time | 3.4s | 2.5s |

The Agent SDK spawns the same CLI binary as a subprocess (`subprocess_cli.py`).
No memory savings. The ~16MB difference is noise.

**OAuth token**: works fine with `CLAUDE_CODE_OAUTH_TOKEN`.

**Conclusion**: switching to the Agent SDK gives a cleaner Python API and slightly
less startup overhead, but does not reduce memory. The only way to cut per-agent
memory is to bypass the CLI entirely and call the Messages API directly — which
means reimplementing tool dispatch and losing session resume, MCP, etc.

Not worth pursuing for concurrency. Scale via container size or separate worker
dyno instead.

---

## 3. Database & Storage

### 3.1 PostgreSQL connection pooling — **DONE**

Replaced raw `psycopg2.connect()` with `ThreadedConnectionPool` (min=1, max=10).
Connections are returned to the pool instead of closed, eliminating TCP overhead
per request.

### 3.2 Compound indexes for hot queries — **DONE**

Added in schema v20:
- `messages(conversation_id, id)` — SSE polling: `WHERE conversation_id = ? AND id > ?`
- `conversations(user_id, updated_at DESC)` — list by user
- `conversations(needs_response) WHERE needs_response = 1` — running check (partial index)

### 3.3 Message pagination

**Status**: planned.

`GET /api/conversations/{id}` loads ALL messages into memory. Conversations with
hundreds of tool_use/tool_result events can be 1MB+.

**Design for natural UX:**
1. Initial load: last 50 messages. Chat anchored to bottom (current behavior).
2. Scroll up: load 50 more (prepend to DOM, maintain scroll position).
3. After 2-3 page loads (~150+ messages): load the full conversation in one request.
   At that point the user is clearly exploring history, and incremental loading
   becomes annoying.
4. The SSE `?after=` parameter already works for streaming — extend the pattern
   to `GET /api/conversations/{id}?last=50&before={msg_id}` for pagination.
5. Needs thorough testing: scroll anchoring, HTMX partial loads, message
   deduplication, correct behavior when streaming is active.

### 3.4 SSE polling → PostgreSQL LISTEN/NOTIFY

**Status**: exploration.

Currently the SSE handler polls every 0.5s (up to 600 times per 5-minute stream).
Each poll = 2 DB queries (messages + needs_response check).

PostgreSQL `LISTEN/NOTIFY` can push notifications when a message is inserted:

```sql
-- In add_message():
NOTIFY new_message, 'conv_id:msg_id'

-- In SSE handler:
LISTEN new_message
-- asyncio waits on the connection until notified (no polling)
```

**Benefits:**
- Near-zero DB load during idle streams (no polling)
- Lower latency (notification arrives in <10ms vs 500ms poll interval)
- Scales to many concurrent streams without proportional DB load

**Considerations:**
- Needs a dedicated connection per SSE stream (doesn't go through the pool)
- `LISTEN` connections are long-lived, need careful lifecycle management
- Falls back to polling (current implementation)
- psycopg2's `select()` or `poll()` integrates with asyncio via `loop.add_reader()`

**Effort**: medium. Worth doing if concurrent streams become a bottleneck.

---

## 4. Interactive Files & S3

### 4.1 Presigned URL redirect (instead of proxying)

**Status**: planned.

Currently `/interactive/{path}` downloads from S3 into memory, then re-serves.
For a 5MB HTML dashboard, that's 5MB of memory and ~200ms of latency per request.

Switch to presigned URL redirect:
```python
url = s3.get_file_url(path, expires_in=300)
return RedirectResponse(url, status_code=302)
```

**Requires CORS on the Scaleway bucket.** Steps:

1. Install the AWS CLI (or use `s3cmd`):
   ```bash
   pip install awscli
   ```

2. Create a CORS config file `cors.json`:
   ```json
   {
     "CORSRules": [
       {
         "AllowedOrigins": ["https://matometa.osc-fr1.scalingo.io"],
         "AllowedMethods": ["GET", "HEAD"],
         "AllowedHeaders": ["*"],
         "MaxAgeSeconds": 3600
       }
     ]
   }
   ```

3. Apply it to the bucket:
   ```bash
   aws s3api put-bucket-cors \
     --bucket YOUR_BUCKET_NAME \
     --cors-configuration file://cors.json \
     --endpoint-url https://s3.fr-par.scw.cloud
   ```
   (Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` env vars first.)

4. Verify:
   ```bash
   aws s3api get-bucket-cors \
     --bucket YOUR_BUCKET_NAME \
     --endpoint-url https://s3.fr-par.scw.cloud
   ```

5. Update `serve_interactive()` to redirect instead of proxy when S3 is available.

**Note:** HTML files with relative asset paths (CSS, JS, images) will break if
the HTML is served from the S3 domain but assets reference `/interactive/...`.
Solutions:
- Use presigned redirects only for non-HTML files (CSV, images, etc.)
- Keep HTML proxied (it's small, and browsers cache it anyway)
- Or ensure interactive apps use only relative paths (no leading `/`)

### 4.2 Cache-Control for static assets

**Status**: planned.

Static assets already use `?v=mtime` cache busting via `static_url()` in templates.
Since the URL changes when the file changes, we can set aggressive caching.

Currently FastAPI's `StaticFiles` uses default headers (no explicit Cache-Control).
Add a middleware or custom static handler:

```python
# All /static/ assets have ?v= busting, so cache forever
app.mount("/static", StaticFiles(directory="web/static"), name="static")
# Add middleware to set Cache-Control on /static/ responses
```

Or simpler: override via the oauth2-proxy/Caddy layer if applicable.

**Interactive assets** (`/interactive/`) already set `max-age=3600` for non-HTML.
These could go higher (1 day? 1 week?) since interactive app deploys are infrequent.

### 4.3 CDN for static & interactive files

**Argument for:**
- Interactive apps shared via conversation links may be accessed by many users
- S3 (Scaleway fr-par) has single-region latency; a CDN adds edge caching
- Offloads bandwidth from the app container entirely
- Scaleway offers a CDN product that fronts Object Storage

**Argument against:**
- The user base is small and France-based — all close to fr-par
- Interactive apps are updated occasionally; cache invalidation adds complexity
- Presigned URLs (4.1) already bypass the app; CDN adds a third layer
- S3 itself already handles high throughput for static files
- Cost vs. benefit doesn't justify it for <100 users

**Verdict:** not worth it now. Revisit if the app goes public or gets heavy
external sharing. Presigned URLs (4.1) give 90% of the benefit.

---

## Summary: Priority Order

| # | Item | Impact | Effort | Status |
|---|------|--------|--------|--------|
| 1 | WEB_CONCURRENCY=1 | High | S | **DONE** |
| 2 | DB connection pooling | High | S | **DONE** |
| 3 | Compound indexes | Medium | S | **DONE** |
| 4 | CLI retry on crash | High | S | **DONE** |
| 5 | Concurrent agent limit | High | S | **DONE** |
| 6 | Presigned URL redirect | Medium | M | Planned |
| 7 | Message pagination | Medium | L | Planned |
| 8 | Static cache headers | Low | S | Planned |
| 9 | LISTEN/NOTIFY for SSE | Medium | L | Exploration |
| 10 | Lighter agent (SDK) | None | — | **Measured: no savings** |
| 11 | Separate PM worker | Medium | M | Deferred |
| 12 | CDN | Low | M | Not needed |
