"""Watch local interactive directory and sync new/modified files to S3.

Runs as a background thread when S3 is configured.
Uses polling to detect file changes and uploads them to S3.
"""

import logging
import threading
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

_watcher_thread = None
_stop_event = threading.Event()


def start_sync_watcher():
    """Start the background file watcher if S3 is configured."""
    global _watcher_thread

    if not config.USE_S3:
        logger.debug("S3 not configured, skipping sync watcher")
        return

    if _watcher_thread is not None and _watcher_thread.is_alive():
        logger.debug("Sync watcher already running")
        return

    # Ensure local directory exists
    config.INTERACTIVE_DIR.mkdir(parents=True, exist_ok=True)

    _stop_event.clear()
    _watcher_thread = threading.Thread(target=_watch_loop, daemon=True)
    _watcher_thread.start()
    logger.info(f"Started S3 sync watcher for {config.INTERACTIVE_DIR}")


def stop_sync_watcher():
    """Stop the background file watcher."""
    global _watcher_thread
    _stop_event.set()
    if _watcher_thread is not None:
        _watcher_thread.join(timeout=5)
        _watcher_thread = None
    logger.info("Stopped S3 sync watcher")


def _watch_loop():
    """Main watch loop using polling (simple, no external dependencies)."""
    from . import s3

    known_files: dict[Path, float] = {}  # path -> mtime

    # Initial sync: single list_objects call instead of N head_object calls
    s3_keys = {entry["path"] for entry in s3.list_files()}
    initial_count = 0
    for path in config.INTERACTIVE_DIR.rglob("*"):
        if path.is_file():
            initial_count += 1
            relative_path = str(path.relative_to(config.INTERACTIVE_DIR))
            if relative_path not in s3_keys:
                _upload_file(path, s3)
            known_files[path] = path.stat().st_mtime

    logger.debug(f"Initial scan: {initial_count} local files, {len(s3_keys)} in S3")

    while not _stop_event.is_set():
        try:
            current_files: dict[Path, float] = {}

            for path in config.INTERACTIVE_DIR.rglob("*"):
                if path.is_file():
                    mtime = path.stat().st_mtime
                    current_files[path] = mtime

                    # Check if new or modified
                    if path not in known_files or known_files[path] < mtime:
                        _upload_file(path, s3)

            known_files = current_files

        except Exception as e:
            logger.error(f"Error in sync watch loop: {e}")

        # Poll every 5 seconds (catches agent-written local files;
        # web app uploads directly to S3)
        _stop_event.wait(5)


def _upload_file(local_path: Path, s3_module):
    """Upload a file to S3."""
    try:
        relative_path = local_path.relative_to(config.INTERACTIVE_DIR)
        content = local_path.read_bytes()

        # Guess content type
        content_type = None
        suffix = local_path.suffix.lower()
        content_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".csv": "text/csv",
        }
        content_type = content_types.get(suffix)

        success = s3_module.upload_file(str(relative_path), content, content_type)
        if success:
            logger.info(f"Synced to S3: {relative_path}")
            if local_path.name == "APP.md":
                from .routes.rapports import invalidate_apps_cache

                invalidate_apps_cache()
        else:
            logger.error(f"Failed to sync to S3: {relative_path}")

    except Exception as e:
        logger.error(f"Error uploading {local_path} to S3: {e}")
