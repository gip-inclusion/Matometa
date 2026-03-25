"""Watch local interactive directory and sync new/modified files to S3.

Runs as a background thread when S3 is configured.
Uses watchdog to detect file changes and uploads them to S3.
"""

import logging
import mimetypes
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

    # Initial sync: upload all existing local files to S3 (if not already there)
    initial_count = 0
    for path in config.INTERACTIVE_DIR.rglob("*"):
        if path.is_file():
            initial_count += 1
            relative_path = path.relative_to(config.INTERACTIVE_DIR)
            # Upload if not in S3
            if not s3.file_exists(str(relative_path)):
                _upload_file(path, s3)
            known_files[path] = path.stat().st_mtime

    logger.debug(f"Initial scan found {initial_count} files")

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

        # Poll every 2 seconds
        _stop_event.wait(2)


def _upload_file(local_path: Path, s3_module):
    try:
        relative_path = local_path.relative_to(config.INTERACTIVE_DIR)
        content = local_path.read_bytes()

        content_type, _ = mimetypes.guess_type(local_path.name)

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
