"""Matometa web application - Flask server with SSE streaming."""

import logging
from pathlib import Path

from flask import Flask, g, request, send_from_directory, abort, redirect, Response

from . import config
from .routes import (
    conversations_bp,
    reports_bp,
    knowledge_bp,
    logs_bp,
    html_bp,
    rapports_bp,
    query_bp,
)

# Configure logging
# On Scalingo (DATABASE_URL set), use stdout only - Scalingo captures it automatically
# Locally, also write to file for persistence
_log_handlers = [logging.StreamHandler()]
if not config.DATABASE_URL:
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _log_handlers.append(logging.FileHandler(config.LOG_FILE))

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)


# =============================================================================
# Middleware
# =============================================================================

@app.before_request
def extract_user_email():
    """
    Extract authenticated user email from oauth2-proxy headers.
    Falls back to DEFAULT_USER for local development.
    """
    g.user_email = (
        request.headers.get("X-Forwarded-Email")
        or config.DEFAULT_USER
    )
    g.user_name = request.headers.get("X-Forwarded-User")


# =============================================================================
# Register Blueprints
# =============================================================================

app.register_blueprint(html_bp)
app.register_blueprint(rapports_bp)
app.register_blueprint(conversations_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(knowledge_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(query_bp)


# =============================================================================
# Static files: /interactive (served from S3 or local data/interactive/)
# =============================================================================


@app.route("/interactive/")
@app.route("/interactive/<path:filename>")
def serve_interactive(filename=""):
    """Serve static files from S3 or local data/interactive directory."""
    if config.USE_S3:
        from . import s3

        # Handle directory requests - try index.html
        if not filename or filename.endswith("/"):
            filename = filename + "index.html"

        # Check if file exists and redirect to presigned URL
        if s3.file_exists(filename):
            url = s3.get_file_url(filename)
            if url:
                return redirect(url)

        # File not found
        abort(404)
    else:
        # Local filesystem fallback
        if not config.INTERACTIVE_DIR.exists():
            config.INTERACTIVE_DIR.mkdir(parents=True, exist_ok=True)

        # If path is a directory, serve index.html
        full_path = config.INTERACTIVE_DIR / filename
        if full_path.is_dir():
            filename = str((full_path / "index.html").relative_to(config.INTERACTIVE_DIR))

        return send_from_directory(config.INTERACTIVE_DIR, filename)


# =============================================================================
# Main
# =============================================================================

def main():
    """Run the development server."""
    print(f"Starting Matometa web server at http://{config.HOST}:{config.PORT}")
    print(f"Agent backend: {config.AGENT_BACKEND}")
    print(f"Working directory: {config.BASE_DIR}")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)


if __name__ == "__main__":
    main()
