"""API routes for Claude authentication."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import claude_auth, claude_credentials, config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")


@router.get("/status")
def status():
    """Get current authentication status.

    Returns backend type so frontend knows whether auth UI is needed.
    Auth is only required for CLI backend, not SDK (which uses API key).
    """
    backend = config.AGENT_BACKEND

    # Non-CLI backends do not require interactive auth
    if not config.USES_CLAUDE_CLI:
        return {
            "backend": backend,
            "auth_required": False,
            "authenticated": True,
        }

    # CLI backend - check credentials
    creds_info = claude_credentials.get_credentials_info()

    if creds_info:
        return {
            "backend": backend,
            "auth_required": True,
            "authenticated": True,
            "subscription_type": creds_info.get("subscription_type"),
            "expires_at": creds_info.get("expires_at"),
        }

    # Check if there's an active auth session
    session_status = claude_auth.get_auth_status()
    if session_status["status"] != "no_session":
        return {
            "backend": backend,
            "auth_required": True,
            "authenticated": False,
            "auth_in_progress": True,
            "session_status": session_status["status"],
            "oauth_url": session_status.get("oauth_url"),
        }

    return {
        "backend": backend,
        "auth_required": True,
        "authenticated": False,
        "auth_in_progress": False,
    }


@router.post("/start")
async def start(request: Request):
    """Start a new authentication session.

    Returns the OAuth URL to open in the browser.

    JSON body (optional): {"force": true} to re-authenticate even if already logged in.
    """
    body = await request.body()
    data = (await request.json()) if body else {}
    force = data.get("force", False)
    result = claude_auth.start_auth(force=force)
    if result.get("status") == "error":
        logger.error("Auth start failed")
        return JSONResponse({"status": "error", "error": "Authentication failed"}, status_code=500)
    return result


@router.post("/complete")
async def complete(request: Request):
    """Complete authentication with the code from OAuth.

    Expects JSON body: {"code": "..."}
    """
    data = await request.json()
    if not data or "code" not in data:
        return JSONResponse(
            {"status": "error", "error": "Missing 'code' in request body"},
            status_code=400,
        )
    result = claude_auth.complete_auth(data["code"])
    if result.get("status") == "error":
        logger.error("Auth completion failed")
        return JSONResponse({"status": "error", "error": "Authentication failed"}, status_code=500)
    return result


@router.post("/cancel")
def cancel():
    """Cancel any active auth session."""
    return claude_auth.cancel_auth()


@router.post("/backup")
def backup():
    """Manually backup credentials to S3."""
    success = claude_credentials.backup_credentials_to_s3()
    if success:
        return {"status": "ok"}
    return JSONResponse({"status": "error", "error": "Backup failed"}, status_code=500)
