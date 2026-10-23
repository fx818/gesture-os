"""Idle. The resting state and the destination of every decay path.

Its enter guard is `always()`: Idle is what you get when nothing else wins, so it must never be
the reason a transition fails. Its sustain is `always()` too — Idle is displaced by a challenger
winning, never by itself giving up.
"""

from __future__ import annotations

from app.arbitration.guards import always
from app.arbitration.registry import ModeSpec
from app.types import ModeId

IDLE = ModeSpec(mode=ModeId.IDLE, priority=0, enter=always(), sustain=always())
