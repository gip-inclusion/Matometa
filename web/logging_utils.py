"""Safe logging formatter to prevent log injection.

Removes null bytes and ANSI escape sequences from log output. Newlines are
kept so messages are never truncated or collapsed to a single line.
"""

import logging
import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class SafeFormatter(logging.Formatter):
    """Logging formatter that neutralizes control characters in output."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        msg = msg.replace("\x00", "")
        msg = _ANSI_RE.sub("", msg)
        return msg


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with the safe formatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(_LOG_FORMAT))
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    logging.root.setLevel(level)
