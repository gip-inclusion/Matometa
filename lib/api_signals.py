"""API call signals for observability.

When the agent runs scripts that call Matomo/Metabase APIs, we want to
capture those calls and display them in the UI sidebar with inspection links.

This module defines the signal protocol:
- API clients emit signals to stdout when making requests
- The backend parses these signals from tool_result content
- Signals are stored as metadata for the UI to display

Signal format:
    [AUTOMETA:API:{"source":"matomo","instance":"inclusion","method":"VisitsSummary.get","url":"https://..."}]

The bracketed format avoids conflicts with JSON output from the APIs.
"""

import json
import re
import sys
from typing import Optional

# Signal pattern for parsing — accepts both legacy MATOMETA and current AUTOMETA prefix
SIGNAL_PATTERN = re.compile(r"\[(?:AUTOMETA|MATOMETA):API:({.*?})\]")


def emit_api_signal(
    source: str,
    instance: str,
    url: str,
    method: Optional[str] = None,
    sql: Optional[str] = None,
    card_id: Optional[int] = None,
) -> None:
    signal = {
        "source": source,
        "instance": instance,
        "url": url,
    }

    if method:
        signal["method"] = method
    if sql:
        # Truncate SQL for display
        signal["sql"] = sql[:500] + "..." if len(sql) > 500 else sql
    if card_id is not None:
        signal["card_id"] = card_id

    # Print to stdout (will be captured in tool_result)
    print(f"[AUTOMETA:API:{json.dumps(signal)}]", file=sys.stdout, flush=True)


def parse_api_signals(content: str) -> list[dict]:
    signals = []
    for match in SIGNAL_PATTERN.finditer(content):
        try:
            signal = json.loads(match.group(1))
            signals.append(signal)
        except json.JSONDecodeError:
            pass
    return signals


def strip_api_signals(content: str) -> str:
    return SIGNAL_PATTERN.sub("", content).strip()
