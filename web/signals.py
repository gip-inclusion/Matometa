"""In-process signal registry for PM → SSE communication.

Replaces DB polling with asyncio.Event signaling. Works because PM and SSE
share the same asyncio event loop (FastAPI lifespan in web/app.py).

Single-process only: the signal registry is a plain dict in memory. Running
multiple uvicorn workers would give each process its own registry, breaking
PM → SSE signaling.
"""

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class ConversationSignal:
    message_event: asyncio.Event = field(default_factory=asyncio.Event)
    finished: bool = False
    counter: int = 0
    created_at: float = field(default_factory=time.monotonic)


class SignalRegistry:
    def __init__(self):
        self._signals: dict[str, ConversationSignal] = {}
        self._pm_alive_at: float = time.monotonic()

    def _get_or_create(self, conv_id: str) -> ConversationSignal:
        if conv_id not in self._signals:
            self._signals[conv_id] = ConversationSignal()
        return self._signals[conv_id]

    # -- Called by PM --

    def notify_message(self, conv_id: str) -> None:
        """Signal that a new message was written for this conversation."""
        sig = self._signals.get(conv_id)
        if sig is None:
            return  # no listener yet — SSE will catch up via DB
        sig.counter += 1
        sig.message_event.set()

    def notify_finished(self, conv_id: str) -> None:
        """Signal that the PM finished processing this conversation.

        Uses _get_or_create because the PM may finish before the SSE handler
        connects (race condition). The SSE handler checks is_finished() on
        entry to handle this case.
        """
        sig = self._get_or_create(conv_id)
        sig.finished = True
        sig.counter += 1
        sig.message_event.set()  # wake SSE so it sees finished=True

    def update_pm_alive(self) -> None:
        """Record that the PM is alive (called alongside DB heartbeat)."""
        self._pm_alive_at = time.monotonic()
        self._evict_stale()

    # -- Called by SSE --

    async def wait_for_message(self, conv_id: str, timeout: float = 3.0) -> bool:
        """Wait for a message signal. Returns True if signaled, False on timeout.

        Uses a monotonic counter as safety net: if a signal fires but the
        event wait times out (e.g. thread-safety edge cases), the counter
        increment is still visible.
        """
        sig = self._get_or_create(conv_id)
        counter_before = sig.counter
        try:
            await asyncio.wait_for(sig.message_event.wait(), timeout=timeout)
            sig.message_event.clear()
            return True
        except asyncio.TimeoutError:
            return sig.counter > counter_before

    def is_finished(self, conv_id: str) -> bool:
        """Check if the PM has finished processing this conversation."""
        sig = self._signals.get(conv_id)
        return sig is not None and sig.finished

    def is_pm_alive(self, max_age: float = 30.0) -> bool:
        """Check if the PM has signaled liveness recently."""
        return (time.monotonic() - self._pm_alive_at) < max_age

    def cleanup(self, conv_id: str) -> None:
        """Remove signal state for a conversation (call on stream end)."""
        self._signals.pop(conv_id, None)

    def _evict_stale(self, max_age: float = 600.0) -> None:
        """Remove finished signals older than max_age seconds.

        Safety net for signals that cleanup() never reaches (SSE never
        connected, or crashed before finally). Called every ~5s from
        update_pm_alive().
        """
        now = time.monotonic()
        stale = [
            cid
            for cid, sig in self._signals.items()
            if sig.finished and (now - sig.created_at) > max_age
        ]
        for cid in stale:
            del self._signals[cid]


signals = SignalRegistry()
