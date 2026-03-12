"""Safe logging formatter to prevent log injection.

Strips newlines, carriage returns, null bytes, and ANSI escape sequences
from all log output so user-controlled values cannot forge log entries
or manipulate terminal displays.
"""

import logging
import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class SafeFormatter(logging.Formatter):
    """Logging formatter that neutralizes control characters in output."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        msg = msg.replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "")
        msg = _ANSI_RE.sub("", msg)
        return msg


def sanitize_log_value(value: object) -> str:
    """Sanitize a value before passing it to a logger.

    Strips control characters that could be used for log injection /
    log forging so that static-analysis tools (CodeQL) can see an
    explicit sanitization boundary at the call-site.
    """
    text = str(value)
    text = text.replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "")
    text = _ANSI_RE.sub("", text)
    return text


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with the safe formatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(_LOG_FORMAT))
    logging.root.handlers.clear()
    logging.root.addHandler(handler)
    logging.root.setLevel(level)
