"""Interactive Claude CLI authentication via pexpect.

Allows web UI to guide users through OAuth flow without direct terminal access.
"""

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Optional

import pexpect

from . import config

logger = logging.getLogger(__name__)

# Regex to extract OAuth URL from Claude output
URL_PATTERN = re.compile(r"https://claude\.ai/oauth/[^\s\x1b\x00-\x1f]+")

# Active auth session (simple in-memory store, only one at a time)
_active_session: Optional["AuthSession"] = None
_session_lock = threading.Lock()


@dataclass
class AuthSession:
    """Represents an ongoing authentication session."""

    process: pexpect.spawn
    oauth_url: Optional[str] = None
    status: str = "starting"  # starting, waiting_for_code, completing, done, error
    error: Optional[str] = None
    output_log: list = field(default_factory=list)


def start_auth(force: bool = False) -> dict:
    """Start a new Claude authentication session.

    Args:
        force: If True, re-authenticate even if credentials exist

    Returns dict with:
        - status: "waiting_for_code", "already_authenticated", or "error"
        - oauth_url: URL to open in browser (if waiting_for_code)
        - error: Error message (if failed)
    """
    global _active_session

    # Check if already authenticated
    from . import claude_credentials

    if claude_credentials.credentials_exist() and not force:
        return {
            "status": "already_authenticated",
            "message": "Credentials already exist. Use force=true to re-authenticate.",
        }

    with _session_lock:
        # Clean up any existing session
        if _active_session:
            _cleanup_session(_active_session)
            _active_session = None

        try:
            # Backup existing credentials
            claude_dir = os.path.expanduser("~/.claude")
            creds_file = os.path.join(claude_dir, ".credentials.json")
            if os.path.exists(creds_file):
                os.rename(creds_file, creds_file + ".backup")
                logger.info("Backed up existing credentials")

            # Spawn claude with pexpect
            # Set TERM to handle the Ink-based UI
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLUMNS"] = "120"
            env["LINES"] = "40"

            child = pexpect.spawn(
                config.CLAUDE_CLI,
                encoding="utf-8",
                timeout=60,
                env=env,
                dimensions=(40, 120),  # rows, cols
            )

            _active_session = AuthSession(process=child, status="starting")

            # Navigate through the setup wizard
            oauth_url = _navigate_to_oauth(child, _active_session)

            if oauth_url:
                _active_session.oauth_url = oauth_url
                _active_session.status = "waiting_for_code"
                return {"status": "waiting_for_code", "oauth_url": oauth_url}
            else:
                _active_session.status = "error"
                _active_session.error = "Could not get OAuth URL"
                return {"status": "error", "error": f"Could not get OAuth URL. Log: {_active_session.output_log[-5:]}"}

        except Exception as e:
            logger.exception("Failed to start auth session")
            if _active_session:
                _cleanup_session(_active_session)
                _active_session = None
            return {"status": "error", "error": str(e)}


def _navigate_to_oauth(child: pexpect.spawn, session: AuthSession) -> Optional[str]:
    """Navigate through Claude's setup wizard to get OAuth URL."""

    def log_output(text):
        # Strip ANSI codes for logging
        clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
        clean = clean.strip()
        if clean:
            session.output_log.append(clean[:200])
            logger.debug(f"Claude: {clean[:100]}")

    def safe_str(val):
        """Convert pexpect output to string safely."""
        if val is None or val is pexpect.TIMEOUT or val is pexpect.EOF:
            return ""
        return str(val)

    import time as time_module

    try:
        # Step 1: Wait for theme selection, press Enter
        logger.info("Waiting for theme selection...")
        index = child.expect(["looks best", pexpect.TIMEOUT, pexpect.EOF], timeout=15)
        log_output(safe_str(child.before) + safe_str(child.after))

        if index == 0:
            logger.info("Theme selection found, pressing Enter")
            time_module.sleep(0.5)  # Wait for UI to stabilize
            child.send("\r")  # Press Enter to select default theme
            time_module.sleep(0.5)

        # Step 2: Wait for login method selection, press Enter
        logger.info("Waiting for login method selection...")
        index = child.expect(
            ["[Ss]elect.*login|[Ll]ogin.*method|Claude account", pexpect.TIMEOUT, pexpect.EOF], timeout=15
        )
        log_output(safe_str(child.before) + safe_str(child.after))

        if index == 0:
            logger.info("Login method found, pressing Enter")
            time_module.sleep(0.5)
            child.send("\r")  # Press Enter to select Claude subscription

        # Step 3: Wait for OAuth URL and then "Paste code" prompt
        logger.info("Waiting for OAuth URL...")

        # Collect output until we see the paste prompt
        collected_output = ""
        found_url = None
        at_paste_prompt = False
        start_time = time_module.time()

        while time_module.time() - start_time < 30:
            try:
                index = child.expect(
                    [r"https://claude\.ai/oauth", "Paste code", pexpect.TIMEOUT, pexpect.EOF], timeout=2
                )
                collected_output += safe_str(child.before) + safe_str(child.after)

                if index == 0:
                    # Found start of URL, extract it but keep waiting for paste prompt
                    logger.debug("Found URL start, continuing to paste prompt...")
                elif index == 1:
                    # Hit paste prompt - we're ready
                    logger.info("At 'Paste code' prompt, ready for code")
                    at_paste_prompt = True
                    break
                elif index == 3:  # EOF
                    logger.debug("Process ended (EOF)")
                    break
            except pexpect.TIMEOUT:
                collected_output += safe_str(child.before)
                continue
            except pexpect.EOF:
                collected_output += safe_str(child.before)
                break

        logger.debug(f"Collected {len(collected_output)} chars of output")

        # Clean and search for URL
        clean_output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", collected_output)
        clean_output = re.sub(r"\x1b\[\?[0-9;]*[a-zA-Z]", "", clean_output)
        clean_output = clean_output.replace("\r\n", "").replace("\n", "").replace("\r", "")

        url_match = URL_PATTERN.search(clean_output)
        if url_match:
            found_url = url_match.group(0)
            logger.info(f"Found OAuth URL ({len(found_url)} chars): {found_url[:80]}...")

        if found_url and at_paste_prompt:
            return found_url

        if found_url and not at_paste_prompt:
            # Got URL but not at prompt yet - wait a bit more for paste prompt
            logger.info("Got URL, waiting for paste prompt...")
            try:
                child.expect(["Paste code"], timeout=10)
                logger.info("Now at 'Paste code' prompt")
                return found_url
            except (pexpect.TIMEOUT, pexpect.EOF):
                logger.warning("Timed out waiting for paste prompt, returning URL anyway")
                return found_url

        logger.warning(f"No URL found. Clean output sample: {clean_output[:500]}")
        return None

    except pexpect.TIMEOUT:
        logger.error("Timeout waiting for Claude CLI")
        log_output(child.before if child.before else "")
        return None
    except pexpect.EOF:
        logger.error("Claude CLI exited unexpectedly")
        log_output(child.before if child.before else "")
        return None


def complete_auth(code: str) -> dict:
    """Complete authentication by sending the code to Claude.

    Args:
        code: The authentication code from the OAuth flow

    Returns dict with:
        - status: "done" or "error"
        - error: Error message (if failed)
    """
    global _active_session

    with _session_lock:
        if not _active_session:
            return {"status": "error", "error": "No active auth session"}

        if _active_session.status != "waiting_for_code":
            return {"status": "error", "error": f"Invalid session status: {_active_session.status}"}

        try:
            _active_session.status = "completing"
            child = _active_session.process

            import time as time_module

            # Wait a moment for the terminal to stabilize
            time_module.sleep(0.5)

            # Check if we're actually at the paste prompt
            logger.info("Verifying we're at paste prompt...")
            try:
                # Look for "Paste code" or ">" prompt indicator
                index = child.expect(["Paste code", ">", pexpect.TIMEOUT], timeout=3)
                if index <= 1:
                    logger.info(f"Confirmed at prompt (index {index})")
            except pexpect.TIMEOUT:
                logger.warning("Could not confirm paste prompt, proceeding anyway")

            # Send the code (use send + newline separately for better control)
            logger.info(f"Sending auth code: {code[:10]}...")
            child.send(code)
            time_module.sleep(0.3)
            child.send("\r")

            # Wait for completion - collect output and look for success indicators
            import time as time_module

            from . import claude_credentials

            def safe_str(val):
                if val is None or val is pexpect.TIMEOUT or val is pexpect.EOF:
                    return ""
                return str(val)

            collected_output = ""
            start_time = time_module.time()

            # Give the auth process time to complete (up to 30 seconds)
            while time_module.time() - start_time < 30:
                try:
                    # Look for success patterns (as separate list items, not regex OR)
                    index = child.expect(
                        ["success", "authenticated", "logged in", "Welcome", "Ready", pexpect.TIMEOUT, pexpect.EOF],
                        timeout=3,
                    )

                    collected_output += safe_str(child.before) + safe_str(child.after)

                    if index <= 4:  # One of the success patterns
                        logger.info(f"Authentication successful! Pattern {index} matched")
                        _active_session.status = "done"
                        claude_credentials.backup_credentials_to_s3()
                        return {"status": "done"}

                    if index == 6:  # EOF - process ended
                        logger.debug("Process ended (EOF)")
                        break

                except pexpect.TIMEOUT:
                    collected_output += safe_str(child.before)
                    # Check if credentials were created during wait
                    if claude_credentials.credentials_exist():
                        logger.info("Credentials file appeared during wait")
                        _active_session.status = "done"
                        claude_credentials.backup_credentials_to_s3()
                        return {"status": "done"}
                    continue
                except pexpect.EOF:
                    collected_output += safe_str(child.before)
                    break

            # Clean and log output for debugging
            clean_output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", collected_output)
            logger.debug(f"Output after code submission: {clean_output[:500]}")

            # Final check for credentials file
            if claude_credentials.credentials_exist():
                logger.info("Credentials file created - auth successful")
                _active_session.status = "done"
                claude_credentials.backup_credentials_to_s3()
                return {"status": "done"}

            _active_session.status = "error"
            return {"status": "error", "error": f"Auth may have failed. Output: {clean_output[:200]}"}

        except Exception as e:
            logger.exception("Failed to complete auth")
            _active_session.status = "error"
            return {"status": "error", "error": str(e)}

        finally:
            _cleanup_session(_active_session)
            _active_session = None


def get_auth_status() -> dict:
    """Get current auth session status."""
    with _session_lock:
        if not _active_session:
            return {"status": "no_session"}
        return {
            "status": _active_session.status,
            "oauth_url": _active_session.oauth_url,
            "error": _active_session.error,
            "log": _active_session.output_log[-10:],
        }


def cancel_auth() -> dict:
    """Cancel any active auth session."""
    global _active_session

    with _session_lock:
        if _active_session:
            _cleanup_session(_active_session)
            _active_session = None
            return {"status": "cancelled"}
        return {"status": "no_session"}


def _cleanup_session(session: AuthSession):
    """Clean up an auth session."""
    try:
        if session.process and session.process.isalive():
            session.process.terminate(force=True)
    except Exception as e:
        logger.debug(f"Error terminating process: {e}")

    # Restore credentials backup if auth failed
    claude_dir = os.path.expanduser("~/.claude")
    creds_backup = os.path.join(claude_dir, ".credentials.json.backup")
    creds_file = os.path.join(claude_dir, ".credentials.json")

    if os.path.exists(creds_backup):
        if session.status != "done" and not os.path.exists(creds_file):
            # Auth failed, restore backup
            os.rename(creds_backup, creds_file)
            logger.info("Restored credentials from backup (auth failed)")
        else:
            # Auth succeeded or creds exist, remove backup
            os.remove(creds_backup)
            logger.debug("Removed credentials backup")
