"""Matometa web application - Flask server with SSE streaming."""

import logging
import re

from flask import Flask, g, request, send_from_directory, abort, redirect

from . import config
from .routes import (
    conversations_bp,
    reports_bp,
    knowledge_bp,
    logs_bp,
    html_bp,
    rapports_bp,
    query_bp,
    auth_bp,
    cron_bp,
    research_bp,
)

# Configure logging (stdout only)
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)


# =============================================================================
# Custom Jinja filters
# =============================================================================

TYPE_ICONS = {
    "❝ Verbatim": "ri-chat-quote-line",
    "👀 Observation": "ri-eye-line",
    "🗣 Entretien": "ri-mic-line",
    "📂 Terrain": "ri-folder-open-line",
    "🤼 Open Lab": "ri-group-line",
    "🧮 Questionnaire / quanti": "ri-bar-chart-box-line",
    "📂 Événement": "ri-calendar-event-line",
    "🗒️ Note": "ri-sticky-note-line",
    "🎤  Retex": "ri-presentation-line",
    "📖 Lecture": "ri-book-read-line",
}
DB_ICONS = {
    "entretiens": "ri-mic-line",
    "thematiques": "ri-bookmark-line",
    "segments": "ri-user-settings-line",
    "profils": "ri-user-line",
    "hypotheses": "ri-question-line",
    "conclusions": "ri-check-double-line",
}


@app.template_filter("regex_replace")
def regex_replace_filter(value, pattern, replacement=""):
    return re.sub(pattern, replacement, str(value))


@app.template_filter("result_icon")
def result_icon_filter(result):
    """Get the icon class for a search result dict."""
    pt = result.get("page_type")
    if pt and pt in TYPE_ICONS:
        return TYPE_ICONS[pt]
    return DB_ICONS.get(result.get("database_key"), "ri-file-text-line")


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
app.register_blueprint(auth_bp)
app.register_blueprint(cron_bp)
app.register_blueprint(research_bp)


# =============================================================================
# Static files: /common (shared CSS/JS frameworks from data/common/)
# =============================================================================


@app.route("/common/<path:filename>")
def serve_common(filename):
    """Serve shared assets from data/common directory."""
    if not config.COMMON_DIR.exists():
        abort(404)
    return send_from_directory(config.COMMON_DIR, filename)


# =============================================================================
# Static files: /interactive (served from S3 or local data/interactive/)
# =============================================================================


@app.route("/interactive/")
@app.route("/interactive/<path:filename>")
def serve_interactive(filename=""):
    """Serve static files from S3 or local data/interactive directory.

    When S3 is enabled, tries S3 first then falls back to local filesystem.
    This allows the agent to write files locally while still serving from S3 when available.
    Content is proxied (not redirected) to avoid exposing internal S3 endpoints.
    """
    from flask import Response
    import mimetypes

    # Block .py files from being served (cron scripts, etc.)
    if filename.endswith(".py"):
        abort(404)

    # Handle directory requests - try index.html
    if not filename or filename.endswith("/"):
        filename = filename + "index.html"

    # Try S3 first if configured
    if config.USE_S3:
        from . import s3

        content = s3.download_file(filename)
        if content is not None:
            # Guess content type
            mime_type, _ = mimetypes.guess_type(filename)
            return Response(content, mimetype=mime_type or "application/octet-stream")

    # Fallback to local filesystem (always, even when S3 is enabled)
    if not config.INTERACTIVE_DIR.exists():
        config.INTERACTIVE_DIR.mkdir(parents=True, exist_ok=True)

    full_path = config.INTERACTIVE_DIR / filename
    if full_path.is_dir():
        if not request.path.endswith("/"):
            return redirect(request.path + "/", code=301)
        filename = str((full_path / "index.html").relative_to(config.INTERACTIVE_DIR))

    if (config.INTERACTIVE_DIR / filename).exists():
        return send_from_directory(config.INTERACTIVE_DIR, filename)

    abort(404)


# =============================================================================
# Main
# =============================================================================

def main():
    """Run the development server."""
    print(f"Starting Matometa web server at http://{config.HOST}:{config.PORT}")
    print(f"Agent backend: {config.AGENT_BACKEND}")
    print(f"Working directory: {config.BASE_DIR}")

    # Restore Claude credentials from S3 if needed
    if config.USES_CLAUDE_CLI:
        from . import claude_credentials
        claude_credentials.restore_credentials_from_s3()

    # Start S3 sync watcher for interactive files
    from . import sync_to_s3
    sync_to_s3.start_sync_watcher()

    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)


if __name__ == "__main__":
    main()
