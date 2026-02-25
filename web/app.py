"""Matometa web application - FastAPI server with SSE streaming."""

import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config

# Configure logging (stdout only)
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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

    # Run process manager in-process (no separate container needed)
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
def serve_interactive(request: Request, filename: str = ""):
    """Serve static files from S3 or local data/interactive directory.

    When S3 is enabled, tries S3 first then falls back to local filesystem.
    Content is proxied (not redirected) to avoid exposing internal S3 endpoints.
    """
    # Block .py files from being served (cron scripts, etc.)
    if filename.endswith(".py"):
        raise HTTPException(status_code=404)

    # Handle directory requests - try index.html
    if not filename or filename.endswith("/"):
        filename = filename + "index.html"

    # Try S3 first if configured
    if config.USE_S3:
        from . import s3

        content = s3.download_file(filename)
        if content is not None:
            mime_type, _ = mimetypes.guess_type(filename)
            return Response(
                content=content,
                media_type=mime_type or "application/octet-stream",
            )

    # Fallback to local filesystem (always, even when S3 is enabled)
    if not config.INTERACTIVE_DIR.exists():
        config.INTERACTIVE_DIR.mkdir(parents=True, exist_ok=True)

    full_path = config.INTERACTIVE_DIR / filename
    if full_path.is_dir():
        if not str(request.url.path).endswith("/"):
            return RedirectResponse(str(request.url.path) + "/", status_code=301)
        filename = str((full_path / "index.html").relative_to(config.INTERACTIVE_DIR))

    local_file = config.INTERACTIVE_DIR / filename
    if local_file.exists():
        return FileResponse(local_file)

    raise HTTPException(status_code=404)


# =============================================================================
# Register Routers
# =============================================================================

from .routes import query, auth, logs, cron, knowledge, reports, rapports, research, html, conversations  # noqa: E402

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
    )


if __name__ == "__main__":
    main()
