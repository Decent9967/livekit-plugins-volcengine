"""Small shared helpers for the volcengine plugin."""

from __future__ import annotations

import time
from collections.abc import Callable


class PeriodicCollector:
    """Accumulate a value and hand the total to ``callback`` every ``duration`` seconds.

    Mirrors ``livekit-plugins-deepgram``'s helper of the same name (also inlined
    by smallestai/xai/inworld): usage events are reported in periodic batches
    instead of once per frame, and ``flush`` forces the pending total out at
    stream end so nothing is lost in the final window.
    """

    def __init__(self, callback: Callable[[float], None], *, duration: float) -> None:
        self._duration = duration
        self._callback = callback
        self._last_flush_time = time.monotonic()
        self._total = 0.0

    def push(self, value: float) -> None:
        self._total += value
        if time.monotonic() - self._last_flush_time >= self._duration:
            self.flush()

    def flush(self) -> None:
        if self._total > 0:
            self._callback(self._total)
            self._total = 0.0
        self._last_flush_time = time.monotonic()
