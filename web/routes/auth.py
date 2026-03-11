"""API routes for Claude authentication."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import claude_auth, claude_credentials, config

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
    return claude_auth.start_auth(force=force)


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
    return claude_auth.complete_auth(data["code"])


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
    return JSONResponse(
        {"status": "error", "error": "Backup failed"}, status_code=500
    )


@router.post("/refresh")
def refresh():
    """Force refresh the OAuth token."""
    if not claude_credentials.token_needs_refresh():
        return {"status": "ok", "message": "Token still valid, no refresh needed"}
    success = claude_credentials.refresh_token()
    if success:
        return {"status": "ok", "message": "Token refreshed"}
    return JSONResponse(
        {"status": "error", "error": "Token refresh failed"}, status_code=500
    )


@router.get("/token-health")
def token_health():
    """Check token expiry status."""
    import time
    info = claude_credentials.get_credentials_info()
    if not info:
        return {"healthy": False, "reason": "no_credentials"}
    expires_at = info.get("expires_at")
    if not expires_at:
        return {"healthy": True, "reason": "no_expiry_info"}
    remaining = (expires_at / 1000) - time.time()
    return {
        "healthy": remaining > claude_credentials.REFRESH_MARGIN_SECONDS,
        "expires_in_seconds": int(remaining),
        "needs_refresh": remaining < claude_credentials.REFRESH_MARGIN_SECONDS,
    }
