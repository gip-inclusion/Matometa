"""Matometa web application - Flask server with SSE streaming."""

import logging

from flask import Flask, g, request

from . import config
from .routes import (
    conversations_bp,
    reports_bp,
    knowledge_bp,
    logs_bp,
    html_bp,
    rapports_bp,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(),
    ],
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
