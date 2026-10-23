"""The judgment port.

Jev sits behind this protocol with a deterministic local fallback implementing the same interface,
so the product runs fully offline and every test in `make ci` uses that path. Swapping, caching,
budgeting and falling back are all decorators over this one method (see `composite.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Protocol, runtime_checkable

from app.decision.questions import PointId, Question


class Source(StrEnum):
    """Where an answer actually came from. Recorded in telemetry so you can see when fallbacks
    started firing rather than discovering it from behaviour."""

    JEV = "jev"
    RULES = "rules"
    CACHE = "cache"
    REPLAY = "replay"
    DENIED = "denied"  # refused by the budget guard


@dataclass(frozen=True, slots=True)
class Judgment:
    key: str
    value: str | float | bool
    confidence: float
    source: Source
    probabilities: Mapping[str, float] | None = None
    latency_ms: float = 0.0

    def acted_on(self, threshold: float) -> bool:
        return self.confidence >= threshold


@dataclass(frozen=True, slots=True)
class JudgmentRequest:
    point: PointId
    state: Mapping[str, str | int | float]
    questions: Mapping[str, Question]
    cache_key: str = ""
    rev: int = 1  # bumped in points.yaml on any prompt edit; participates in the cache key


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    name: str
    available: bool
    detail: str = ""
    calls: int = 0
    failures: int = 0


@runtime_checkable
class JudgmentProvider(Protocol):
    def judge(self, req: JudgmentRequest) -> Mapping[str, Judgment]: ...
    def health(self) -> ProviderHealth: ...


class ProviderError(RuntimeError):
    """Any failure to obtain a judgment. Callers fall back; they never propagate this to the loop."""


def noul_confidence(noul: float) -> float:
    """Derive a confidence for a Noul.

    `NoulAnswer` carries only `noul` — verified against typesafe-sdk 0.6.0, and contrary to the
    published docs, which describe a `confidence` on every answer. So we compute one: 0.5 is
    maximal uncertainty, 0.0 and 1.0 are maximal certainty.

    This matters because the whole confidence-gating design assumes every judgment reports one.
    Keeping the derivation in a single named function means that if the SDK later grows a real
    `confidence`, exactly one place changes.
    """
    return abs(noul - 0.5) * 2.0
