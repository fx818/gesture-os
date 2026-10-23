"""Arbiter state and its output. Frozen, so a step can be replayed or compared."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from app.intents import Intent
from app.types import ModeId


@dataclass(frozen=True, slots=True)
class ArbiterTrace:
    """Why the engine did what it did. Feeds the confidence HUD and, later, Jev point F's
    misfire post-mortem — which needs to know not just what fired but what nearly fired."""

    scores: Mapping[ModeId, float]
    winner: ModeId | None
    blocked_by: str = ""  # "dwell" | "streak" | "refractory" | ""

    def top(self) -> tuple[ModeId, float] | None:
        if not self.scores:
            return None
        return max(self.scores.items(), key=lambda kv: kv[1])


@dataclass(frozen=True, slots=True)
class ArbiterState:
    mode: ModeId = ModeId.IDLE
    entered_t_ms: float = 0.0
    confidence: float = 0.0
    candidate: ModeId | None = None
    candidate_streak: int = 0
    refractory_until: Mapping[ModeId, float] = field(default_factory=dict)
    # When each mode's enter guard FIRST became continuously true. Cleared the moment it drops.
    # This is what makes a dwell a property of the state machine rather than of the window.
    hold_since: Mapping[ModeId, float] = field(default_factory=dict)
    mode_data: Mapping[str, object] = field(default_factory=dict)

    def with_mode(self, mode: ModeId, t_ms: float, confidence: float) -> ArbiterState:
        refractory = dict(self.refractory_until)
        return ArbiterState(
            mode=mode,
            entered_t_ms=t_ms,
            confidence=confidence,
            candidate=None,
            candidate_streak=0,
            refractory_until=refractory,
            mode_data={},
        )


@dataclass(frozen=True, slots=True)
class StepResult:
    state: ArbiterState
    intents: tuple[Intent, ...]
    trace: ArbiterTrace
