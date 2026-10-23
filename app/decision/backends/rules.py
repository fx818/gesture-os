"""Deterministic offline judgment. No network, no key, no latency.

Every Jev point ships with a rule table beside its question set, so the two are reviewed together
and the fallback can never silently rot. This is what `--offline` runs, what `make ci` runs, and
what a low-confidence Jev answer falls back to.

Confidences here are honest, not flattering: a regex match on a known application name is genuinely
worth ~0.8, and "no rule matched" is 0.0, not a guess. The gate downstream is the same code path
either way, so a dishonest confidence here would silently promote a guess into an action.
"""

from __future__ import annotations

from typing import Callable, Mapping

from app.decision.provider import Judgment, JudgmentRequest, ProviderHealth, Source
from app.decision.questions import PointId

FallbackFn = Callable[[JudgmentRequest], Mapping[str, Judgment]]

_FALLBACKS: dict[PointId, FallbackFn] = {}


def register(point: PointId) -> Callable[[FallbackFn], FallbackFn]:
    def deco(fn: FallbackFn) -> FallbackFn:
        _FALLBACKS[point] = fn
        return fn

    return deco


def _unknown(req: JudgmentRequest) -> Mapping[str, Judgment]:
    """Last resort: answer every question with its least-committal value at zero confidence.

    Returning *something* matters — a provider that raises would force every caller to handle
    absence, and the confidence gate already handles "I don't know" correctly.
    """
    from app.decision.questions import ChoiceQ, NoulQ, ScoreQ

    out: dict[str, Judgment] = {}
    for key, q in req.questions.items():
        if isinstance(q, ChoiceQ):
            value: str | float = "unknown" if "unknown" in q.options else next(iter(q.options))
        elif isinstance(q, ScoreQ):
            value = 0.0
        elif isinstance(q, NoulQ):
            value = 0.5
        else:
            value = 0.0
        out[key] = Judgment(key=key, value=value, confidence=0.0, source=Source.RULES)
    return out


class RuleProvider:
    def __init__(self) -> None:
        self._calls = 0

    def judge(self, req: JudgmentRequest) -> Mapping[str, Judgment]:
        self._calls += 1
        fn = _FALLBACKS.get(req.point)
        return fn(req) if fn else _unknown(req)

    def health(self) -> ProviderHealth:
        return ProviderHealth(name="rules", available=True, calls=self._calls)
