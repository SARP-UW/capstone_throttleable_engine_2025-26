from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import threading


@dataclass(slots=True)
class SystemState:
    """Global (non-sensor) system state.

    This is the shared state that *F3 owns* (high-level mode, abort latch, etc.).

    Keep this small at first; it is shared across threads.
    """

    # High-level mode/state-machine state.
    # Example set only; choose the exact set that matches your F3 design.
    mode: str = "IDLE"  # IDLE / ARMED / FILL / FIRE / THROTTLE / SAFE / ABORT

    # F3 should latch aborts so they persist even if inputs recover.
    abort_latched: bool = False

    # Human-readable debug string (GUI display / logs).
    last_message: str = ""


class SystemStateStore:
    """Mutex-protected store for SystemState.

    Concurrency contract:
      - Any loop may call snapshot() at any time.
      - F3 loop should be the *only* writer of mode/abort_latched.
      - Other loops may write last_message (optional) for observability.

    Why a store instead of sharing SystemState directly?
      - Centralizes locking.
      - Makes it hard to accidentally read/write without the mutex.
      - Lets you evolve internals without changing every loop.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = SystemState()

    def update(self, **fields: Any) -> None:
        """Atomically update one or more SystemState fields."""

        with self._lock:
            for key, value in fields.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)

    def snapshot(self) -> SystemState:
        """Return a stable copy safe to use outside the lock."""

        with self._lock:
            return SystemState(
                mode=self._state.mode,
                abort_latched=self._state.abort_latched,
                last_message=self._state.last_message,
            )
