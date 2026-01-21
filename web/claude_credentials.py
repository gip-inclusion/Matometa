"""Manage Claude Code credentials persistence via S3.

On container startup, downloads credentials from S3 if available.
After successful authentication, uploads credentials to S3.
"""

import json
import logging
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

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
    """Check if Claude credentials exist locally."""
    return CREDENTIALS_FILE.exists()


def get_credentials_info() -> dict | None:
    """Get non-sensitive info about current credentials.

    Set SKIP_CLI_AUTH_CHECK=true when running outside container (e.g., local dev
    with `.venv/bin/python -m web.app`) where the user's Claude CLI is already
    authenticated through their own setup.
    """
    import os

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
