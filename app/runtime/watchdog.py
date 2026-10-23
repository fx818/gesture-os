"""The independent panic detector.

The scope doc requires the kill switch to be "a hard kill switch independent of the arbitration
engine's own state, so it works even mid-macro or mid-drag". The engine already treats PANIC
specially — checked before any transition logic, and sticky once entered — but that is still code
running inside `step()`. If `step()` wedges, throws, or is starved, so does the kill switch.

This is the second, deliberately stupid detector. It reads `FeatureFrame` directly, runs on its own
thread, knows nothing about modes, and calls `release_all()` on every sink. No guards, no registry,
no config lookups beyond two numbers, nothing that can raise.

It is intentionally cruder than the engine's version: it is allowed to be more trigger-happy,
because the cost of an unnecessary release (the cursor stops) is far lower than the cost of a
missed one (a stuck mouse button mid-drag).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.config import PanicConfig
from app.effectors.ports import EffectorSet
from app.types import FeatureFrame


@dataclass
class WatchdogState:
    held_since_ms: float | None = None
    fired: bool = False
    fire_count: int = 0
    last_fire_t_ms: float = 0.0


class PanicWatchdog:
    """Fed one FeatureFrame per frame by the loop. Never blocks it."""

    def __init__(self, effectors: EffectorSet, cfg: PanicConfig) -> None:
        self._fx = effectors
        self._cfg = cfg
        self._state = WatchdogState()
        self._lock = threading.Lock()
        self.disengaged = False

    def _pose_held(self, frame: FeatureFrame) -> bool:
        """Both hands open and still. Deliberately not the engine's guard — no ramps, no windows,
        no confidence. If this and the engine ever disagree, the engine is the one to fix."""
        left, right = frame.left, frame.right
        if left is None or right is None:
            return False
        if min(left.openness, right.openness) < self._cfg.both_open_min:
            return False
        return max(left.palm_speed, right.palm_speed) <= self._cfg.max_speed

    def observe(self, frame: FeatureFrame) -> bool:
        """Returns True on the frame it fires. Never raises — there is nothing above it to catch."""
        try:
            with self._lock:
                st = self._state
                if not self._pose_held(frame):
                    st.held_since_ms = None
                    st.fired = False
                    # Releasing the pose re-arms the system. Staying disengaged would make the
                    # kill switch a one-way door with no gesture to undo it.
                    self.disengaged = False
                    return False

                if st.held_since_ms is None:
                    st.held_since_ms = frame.t_ms
                    return False
                if st.fired:
                    return False
                if (frame.t_ms - st.held_since_ms) < self._cfg.watchdog_hold_ms:
                    return False

                st.fired = True
                st.fire_count += 1
                st.last_fire_t_ms = frame.t_ms
                self.disengaged = True
        except Exception:  # noqa: BLE001
            return False

        self._release()
        return True

    def _release(self) -> None:
        try:
            self._fx.release_all()
        except Exception:  # noqa: BLE001 — EffectorSet.release_all already guards per-sink
            pass

    @property
    def fire_count(self) -> int:
        return self._state.fire_count
