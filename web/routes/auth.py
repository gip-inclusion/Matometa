"""API routes for Claude authentication."""

from flask import Blueprint, jsonify, request

from .. import claude_auth, claude_credentials, config

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.route("/status", methods=["GET"])
def status():
    """Get current authentication status.

    Returns backend type so frontend knows whether auth UI is needed.
    Auth is only required for CLI backend, not SDK (which uses API key).
    """
    backend = config.AGENT_BACKEND

    # SDK backend doesn't need interactive auth
    if backend != "cli":
        return jsonify({
            "backend": backend,
            "auth_required": False,
            "authenticated": True,  # SDK uses API key, always "authenticated"
        })

    # CLI backend - check credentials
    creds_info = claude_credentials.get_credentials_info()

    if creds_info:
        return jsonify({
            "backend": backend,
            "auth_required": True,
            "authenticated": True,
            "subscription_type": creds_info.get("subscription_type"),
            "expires_at": creds_info.get("expires_at"),
        })

    # Check if there's an active auth session
    session_status = claude_auth.get_auth_status()
    if session_status["status"] != "no_session":
        return jsonify({
            "backend": backend,
            "auth_required": True,
            "authenticated": False,
            "auth_in_progress": True,
            "session_status": session_status["status"],
            "oauth_url": session_status.get("oauth_url"),
        })

    return jsonify({
        "backend": backend,
        "auth_required": True,
        "authenticated": False,
        "auth_in_progress": False,
    })


@bp.route("/start", methods=["POST"])
def start():
    """Start a new authentication session.

    Returns the OAuth URL to open in the browser.

    JSON body (optional): {"force": true} to re-authenticate even if already logged in.
    """
    data = request.get_json(silent=True) or {}
    force = data.get("force", False)
    result = claude_auth.start_auth(force=force)
    return jsonify(result)


@bp.route("/complete", methods=["POST"])
def complete():
    """Complete authentication with the code from OAuth.

    Expects JSON body: {"code": "..."}
    """
    data = request.get_json()
    if not data or "code" not in data:
        return jsonify({"status": "error", "error": "Missing 'code' in request body"}), 400

    result = claude_auth.complete_auth(data["code"])
    return jsonify(result)


@bp.route("/cancel", methods=["POST"])
def cancel():
    """Cancel any active auth session."""
    result = claude_auth.cancel_auth()
    return jsonify(result)


@bp.route("/backup", methods=["POST"])
def backup():
    """Manually backup credentials to S3."""
    success = claude_credentials.backup_credentials_to_s3()
    if success:
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "error": "Backup failed"}), 500
