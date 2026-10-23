"""The kill switch.

Checked OUTSIDE the state machine, before any transition logic runs, so it works mid-macro and
mid-drag and cannot be swallowed by a mode that happens to be sustaining. The scope doc is explicit
that this must be "independent of the arbitration engine's own state"; this module is half of that
guarantee, and `runtime/watchdog.py` (P5) is the other half — a second detector that does not go
through `step()` at all.
"""

from __future__ import annotations

from app.arbitration.guards import both_hands_open, for_fraction
from app.config import Config
from app.types import DecisionContext, FeatureWindow, ModeId

# Instantaneous pose. The 300ms hold is enforced by the engine via
# `arbitration.hold_ms.panic`, so it can span more than one feature window.
_GUARD = for_fraction(
    ModeId.PANIC, both_hands_open("panic.both_open_min", "panic.max_speed")
)


def check(window: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
    return _GUARD(window, ctx, cfg)
