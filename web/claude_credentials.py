"""Manage Claude Code credentials persistence via S3.

On container startup, downloads credentials from S3 if available.
After successful authentication, uploads credentials to S3.
Proactively refreshes OAuth tokens before expiry.
"""

import json
import logging
import time
from pathlib import Path

import requests as http_requests

from . import config

logger = logging.getLogger(__name__)

TOKEN_ENDPOINT = "https://platform.claude.com/v1/oauth/token"
OAUTH_CLIENT_ID = config.OAUTH_CLIENT_ID
REFRESH_MARGIN_SECONDS = 3600  # Refresh when < 1 hour remaining

# Claude credentials location inside container
CLAUDE_DIR = Path.home() / ".claude"
CREDENTIALS_FILE = CLAUDE_DIR / ".credentials.json"
S3_CREDENTIALS_KEY = "claude-credentials.json"  # Stored outside interactive/ prefix


def restore_credentials_from_s3() -> bool:
    """Download credentials from S3 if they exist and local credentials are missing.

    Returns True if credentials were restored or already exist locally.
    """
    if not config.USE_S3:
        logger.debug("S3 not configured, skipping credential restore")
        return CREDENTIALS_FILE.exists()

    if CREDENTIALS_FILE.exists():
        logger.debug("Local credentials already exist")
        return True

    from . import s3

    try:
        # Download from S3 (outside the interactive/ prefix)
        content = _download_credentials_from_s3(s3)
        if content is None:
            logger.info("No credentials found in S3")
            return False

        # Ensure directory exists
        CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

        # Write credentials
        CREDENTIALS_FILE.write_bytes(content)
        CREDENTIALS_FILE.chmod(0o600)  # Secure permissions

        logger.info("Restored Claude credentials from S3")
        return True

    except Exception as e:
        logger.error(f"Failed to restore credentials from S3: {e}")
        return False


def backup_credentials_to_s3() -> bool:
    """Upload current credentials to S3 for persistence.

    Returns True if backup succeeded.
    """
    if not config.USE_S3:
        logger.debug("S3 not configured, skipping credential backup")
        return False

    if not CREDENTIALS_FILE.exists():
        logger.warning("No credentials to backup")
        return False

    from . import s3

    try:
        content = CREDENTIALS_FILE.read_bytes()
        success = _upload_credentials_to_s3(s3, content)

        if success:
            logger.info("Backed up Claude credentials to S3")
        return success

    except Exception as e:
        logger.error(f"Failed to backup credentials to S3: {e}")
        return False


def credentials_exist() -> bool:
    """Check if Claude credentials exist (file or env var)."""
    import os
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    return CREDENTIALS_FILE.exists()


def get_credentials_info() -> dict | None:
    """Get non-sensitive info about current credentials.

    Set SKIP_CLI_AUTH_CHECK=true when running outside container (e.g., local dev
    with `.venv/bin/python -m web.app`) where the user's Claude CLI is already
    authenticated through their own setup.
    """
    import os

    # CLAUDE_CODE_OAUTH_TOKEN env var = authenticated via long-lived token
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        return {"authenticated": True, "oauth_token": True}

    if not CREDENTIALS_FILE.exists():
        # Local dev outside container: assume CLI is authenticated
        if os.getenv("SKIP_CLI_AUTH_CHECK", "").lower() == "true":
            return {"authenticated": True, "local_dev": True}
        return None

    try:
        data = json.loads(CREDENTIALS_FILE.read_text())
        oauth = data.get("claudeAiOauth", {})
        return {
            "authenticated": True,
            "subscription_type": oauth.get("subscriptionType"),
            "scopes": oauth.get("scopes", []),
            "expires_at": oauth.get("expiresAt"),
        }
    except Exception:
        return None


def write_credentials(oauth_data: dict) -> bool:
    """Write OAuth credentials to the credentials file.

    Args:
        oauth_data: Dict with accessToken, refreshToken, expiresAt, scopes, etc.

    Returns True if successful.
    """
    try:
        CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

        credentials = {"claudeAiOauth": oauth_data}
        CREDENTIALS_FILE.write_text(json.dumps(credentials, indent=2))
        CREDENTIALS_FILE.chmod(0o600)

        # Backup to S3 immediately
        backup_credentials_to_s3()

        logger.info("Wrote Claude credentials")
        return True

    except Exception as e:
        logger.error(f"Failed to write credentials: {e}")
        return False


# =============================================================================
# Token refresh
# =============================================================================


def token_needs_refresh() -> bool:
    """Check if the current OAuth token is near expiry."""
    if not CREDENTIALS_FILE.exists():
        return False
    try:
        data = json.loads(CREDENTIALS_FILE.read_text())
        oauth = data.get("claudeAiOauth", {})
        expires_at = oauth.get("expiresAt")
        if not expires_at:
            return False
        remaining = (expires_at / 1000) - time.time()
        return remaining < REFRESH_MARGIN_SECONDS
    except Exception:
        return False


def refresh_token() -> bool:
    """Refresh the OAuth access token using the stored refresh token.

    Returns True if refresh succeeded, False otherwise.
    """
    if not CREDENTIALS_FILE.exists():
        logger.warning("No credentials file to refresh")
        return False

    try:
        data = json.loads(CREDENTIALS_FILE.read_text())
        oauth = data.get("claudeAiOauth", {})
        refresh_tok = oauth.get("refreshToken")

        if not refresh_tok:
            logger.warning("No refresh token available")
            return False

        remaining = (oauth.get("expiresAt", 0) / 1000) - time.time()
        logger.info("Token expires in %.0f seconds, attempting refresh...", remaining)

        resp = http_requests.post(
            TOKEN_ENDPOINT,
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_tok,
                "client_id": OAUTH_CLIENT_ID,
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

        if resp.status_code != 200:
            logger.error("Token refresh failed: HTTP %d — %s", resp.status_code, resp.text[:200])
            return False

        new_data = resp.json()

        # Update credentials with new tokens
        oauth["accessToken"] = new_data["access_token"]
        if "refresh_token" in new_data:
            oauth["refreshToken"] = new_data["refresh_token"]
        if "expires_in" in new_data:
            oauth["expiresAt"] = int((time.time() + new_data["expires_in"]) * 1000)

        data["claudeAiOauth"] = oauth
        CREDENTIALS_FILE.write_text(json.dumps(data, indent=2))
        CREDENTIALS_FILE.chmod(0o600)

        new_remaining = (oauth["expiresAt"] / 1000) - time.time()
        logger.info("Token refreshed successfully, new expiry in %.0f seconds", new_remaining)

        # Backup refreshed credentials
        backup_credentials_to_s3()
        return True

    except Exception as e:
        logger.error("Token refresh error: %s", e)
        return False


def ensure_valid_token() -> bool:
    """Check token expiry and refresh if needed. Called periodically.

    Returns True if token is valid (either still fresh or successfully refreshed).
    """
    import os
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        return True  # Env var token, not our responsibility

    if not CREDENTIALS_FILE.exists():
        return False

    if token_needs_refresh():
        return refresh_token()

    return True


# Internal helpers using raw S3 client to bypass the interactive/ prefix

def _download_credentials_from_s3(s3_module) -> bytes | None:
    """Download credentials directly from S3 bucket root."""
    try:
        response = s3_module._s3_client.get_object(
            Bucket=config.S3_BUCKET,
            Key=S3_CREDENTIALS_KEY
        )
        return response["Body"].read()
    except Exception as e:
        if "NoSuchKey" in str(e) or "404" in str(e):
            return None
        raise


def _upload_credentials_to_s3(s3_module, content: bytes) -> bool:
    """Upload credentials directly to S3 bucket root."""
    try:
        s3_module._s3_client.put_object(
            Bucket=config.S3_BUCKET,
            Key=S3_CREDENTIALS_KEY,
            Body=content,
            ContentType="application/json",
        )
        return True
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        return False
