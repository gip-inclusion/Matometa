"""Matometa web application - FastAPI server with SSE streaming."""

import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .deps import get_current_user

# Extensions safe to serve via presigned URL redirect (no sensitive data)
_STATIC_ASSET_EXTS = frozenset({
    ".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".gif",
    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map",
})

# Configure logging (stdout only)
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Silence noisy third-party loggers (boto generates ~30 debug lines per S3 request)
for _logger_name in ("botocore", "boto3", "urllib3", "s3transfer"):
    logging.getLogger(_logger_name).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown tasks."""
    # Restore Claude credentials from S3 if needed
    if config.USES_CLAUDE_CLI:
        from . import claude_credentials

        claude_credentials.restore_credentials_from_s3()

    # Start S3 sync watcher for interactive files
    from . import sync_to_s3

    sync_to_s3.start_sync_watcher()

    # Warm the interactive apps cache (avoids N+1 S3 calls on first request)
    if config.USE_S3:
        from .routes.rapports import scan_interactive_apps

        await asyncio.to_thread(scan_interactive_apps)

    # Run process manager in-process (no separate container needed).
    # Single-worker constraint: PM and SSE share an in-memory signal registry
    # (web/signals.py), so multiple workers would each get their own registry
    # and PM signals would not reach SSE handlers in other processes.
    from .pm import ProcessManager

    pm = ProcessManager()
    pm_task = asyncio.create_task(pm.run())

    yield

    pm_task.cancel()
    try:
        await pm_task
    except asyncio.CancelledError:
        pass


# Create FastAPI app
app = FastAPI(lifespan=lifespan)


# =============================================================================
# Static files
# =============================================================================

app.mount("/static", StaticFiles(directory="web/static"), name="static")

if config.COMMON_DIR.exists():
    app.mount("/common", StaticFiles(directory=str(config.COMMON_DIR)), name="common")


# =============================================================================
# Interactive files: /interactive/ (served from S3 or local data/interactive/)
# =============================================================================


@app.get("/interactive/{filename:path}")
@app.get("/interactive/")
def serve_interactive(
    request: Request,
    filename: str = "",
    user_email: str = Depends(get_current_user),
):
    """Serve interactive files to authenticated users.

    Auth is checked on every request (via oauth2-proxy in prod,
    DEFAULT_USER in dev).  Static assets (CSS/JS/images) are served
    via presigned URL redirect (5 min TTL); other files are streamed
    through the app in 64 KB chunks.

    File state matrix (USE_S3=True):
      S3 hit, static asset → 307 presigned URL redirect
      S3 hit, other        → StreamingResponse (bounded memory)
      S3 miss, local hit   → FileResponse (not yet synced)
      S3 miss, local dir   → 301 redirect to trailing slash
      both miss            → 404
    """
    # Block .py files from being served
    if filename.endswith(".py"):
        raise HTTPException(status_code=404)

    # Handle directory requests — try index.html
    if not filename or filename.endswith("/"):
        filename = filename + "index.html"

    # Path traversal protection
    interactive_root = config.INTERACTIVE_DIR.resolve()
    try:
        resolved = (config.INTERACTIVE_DIR / filename).resolve()
    except (ValueError, OSError):
        raise HTTPException(status_code=404)
    if not resolved.is_relative_to(interactive_root):
        raise HTTPException(status_code=404)

    # MIME type and cache policy
    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"
    # HTML revalidates every time; assets cache for 1 hour
    cache_control = "no-cache" if mime_type == "text/html" else "public, max-age=3600"

    # Try S3 first if configured
    if config.USE_S3:
        from . import s3

        # Static assets: redirect to a short-lived presigned URL (5 min)
        # — offloads bandwidth from the app server, S3 serves directly
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix in _STATIC_ASSET_EXTS and s3.file_exists(filename):
            url = s3.get_file_url(filename, expires_in=300)
            if url is not None:
                return RedirectResponse(url, status_code=307, headers={
                    "Cache-Control": "private, max-age=300",
                    "Referrer-Policy": "no-referrer",
                })

        # HTML, CSV, JSON, etc.: stream chunks (bounded memory, S3 not exposed)
        stream = s3.stream_file(filename)
        if stream is not None:
            return StreamingResponse(
                stream,
                media_type=mime_type,
                headers={"Cache-Control": cache_control},
            )

    # Fallback to local filesystem (always, even when S3 is enabled —
    # covers the ≤2s window before sync_to_s3 uploads a new file)
    if resolved.is_dir():
        if not str(request.url.path).endswith("/"):
            return RedirectResponse(str(request.url.path) + "/", status_code=301)
        resolved = resolved / "index.html"

    if resolved.is_file():
        return FileResponse(resolved, headers={"Cache-Control": cache_control})

    raise HTTPException(status_code=404)


# =============================================================================
# Register Routers
# =============================================================================

from .routes import auth, conversations, cron, html, knowledge, logs, query, rapports, reports, research  # noqa: E402

app.include_router(query.router)
app.include_router(auth.router)
app.include_router(logs.router)
app.include_router(knowledge.router)
app.include_router(reports.router)
app.include_router(research.router)
app.include_router(conversations.router)
# Template-serving routers last (they have catch-all-ish paths)
app.include_router(rapports.router)
app.include_router(cron.router)
app.include_router(html.router)


# =============================================================================
# Main
# =============================================================================


def main():
    """Run the development server."""
    import uvicorn

    print(f"Starting Matometa web server at http://{config.HOST}:{config.PORT}")
    print(f"Agent backend: {config.AGENT_BACKEND}")
    print(f"Working directory: {config.BASE_DIR}")

    uvicorn.run(
        "web.app:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG,
        workers=1,  # required: PM ↔ SSE signals are in-process (see lifespan)
    )


if __name__ == "__main__":
    main()
