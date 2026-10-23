"""Provider decorators. Offline is a composition, not a code path.

    live    = CachingProvider(BudgetedProvider(FallbackProvider(TypeSafe, Rules)))
    offline = CachingProvider(Rules)

Nothing outside `runtime/wiring.py` knows which one it has.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Mapping

from app.decision.cache import SqliteCache
from app.decision.provider import (
    Judgment,
    JudgmentProvider,
    JudgmentRequest,
    ProviderError,
    ProviderHealth,
)


class CachingProvider:
    """Read-through cache.

    Caches a result as long as *something* in it came from the model. The naive rule — refuse to
    cache anything containing a rules answer — looked safer and was actively wrong: a point that
    fans out several questions will routinely have one of them fall back (a Noul whose derived
    confidence is low, say), and that would mean nothing was ever cached and every focus change
    paid a full round trip. Measured: 1.2 s per call instead of 0.

    What must NOT be cached is a total outage, where every answer came from rules. Freezing that
    in place would keep serving a degraded answer long after Jev came back.
    """

    def __init__(
        self,
        inner: JudgmentProvider,
        cache: SqliteCache,
        *,
        ttl_s: float = 86400.0,
    ) -> None:  # noqa: D107
        self._inner = inner
        self._cache = cache
        self._ttl = ttl_s
        self.hits = 0
        self.misses = 0

    def judge(self, req: JudgmentRequest) -> Mapping[str, Judgment]:
        if req.cache_key:
            hit = self._cache.get(req.point.value, req.cache_key, self._ttl)
            if hit is not None:
                self.hits += 1
                return hit
        self.misses += 1
        answers = self._inner.judge(req)
        if req.cache_key and answers and self._cacheable(answers):
            self._cache.put(req.point.value, req.cache_key, answers)
        return answers

    @staticmethod
    def _cacheable(answers: Mapping[str, Judgment]) -> bool:
        from app.decision.provider import Source

        if any(j.source is Source.DENIED for j in answers.values()):
            return False
        return any(j.source in (Source.JEV, Source.REPLAY) for j in answers.values())

    def health(self) -> ProviderHealth:
        h = self._inner.health()
        return ProviderHealth(
            name=f"cached({h.name})",
            available=h.available,
            detail=f"hits={self.hits} misses={self.misses}",
            calls=h.calls,
            failures=h.failures,
        )


class BudgetedProvider:
    """Token bucket, well under the published 1200 req/min ceiling, plus a per-session cap.

    Exists because a bug in an event loop is the realistic way to exceed a rate limit, not user
    behaviour: the real call rate is roughly 200 focus changes a day. A refusal here raises, so
    the FallbackProvider above it degrades to rules rather than the loop stalling on a 429.
    """

    def __init__(
        self,
        inner: JudgmentProvider,
        *,
        per_minute: int = 300,
        session_cap: int = 5000,
    ) -> None:
        self._inner = inner
        self._per_minute = per_minute
        self._session_cap = session_cap
        self._window: deque[float] = deque()
        self._total = 0

    def judge(self, req: JudgmentRequest) -> Mapping[str, Judgment]:
        now = time.monotonic()
        while self._window and now - self._window[0] > 60.0:
            self._window.popleft()
        if len(self._window) >= self._per_minute:
            raise ProviderError(f"rate budget exhausted ({self._per_minute}/min)")
        if self._total >= self._session_cap:
            raise ProviderError(f"session budget exhausted ({self._session_cap} calls)")
        self._window.append(now)
        self._total += 1
        return self._inner.judge(req)

    def health(self) -> ProviderHealth:
        h = self._inner.health()
        return ProviderHealth(
            name=f"budgeted({h.name})",
            available=h.available,
            detail=f"{len(self._window)}/{self._per_minute} per min, {self._total} this session",
            calls=h.calls,
            failures=h.failures,
        )


class FallbackProvider:
    """Primary, then secondary — on error, on timeout, or on low confidence.

    `act_threshold` is the confidence below which the primary's answer is not worth acting on.
    Note the secondary's answer is returned *as* the answer: callers still gate on confidence, and
    the rules provider reports honest (often low) numbers, so a genuinely unknown case stays
    unknown rather than being laundered into certainty.
    """

    def __init__(
        self,
        primary: JudgmentProvider,
        secondary: JudgmentProvider,
        *,
        act_threshold: float = 0.9,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._act_threshold = act_threshold
        self.fallbacks = 0

    def judge(self, req: JudgmentRequest) -> Mapping[str, Judgment]:
        try:
            answers = self._primary.judge(req)
        except ProviderError:
            self.fallbacks += 1
            return self._secondary.judge(req)

        if not answers:
            self.fallbacks += 1
            return self._secondary.judge(req)

        # Gate on the weakest answer only to decide whether consulting the (free, local)
        # secondary is worth it. The actual substitution below is per-key, so one uncertain
        # question never discards a confident one.
        #
        # Caveat worth remembering: a Noul's confidence is DERIVED (see provider.noul_confidence)
        # because the SDK does not report one, so nouls read as less confident than a Choice
        # answering with the same conviction. That asymmetry makes this gate fire often.
        weakest = min(j.confidence for j in answers.values())
        if weakest < self._act_threshold:
            alt = self._secondary.judge(req)
            # Only prefer the fallback where it is genuinely more confident. A rules table that
            # knows `ptyxis` is a terminal beats Jev's 0.53 "unknown"; a rules table that knows
            # nothing (0.0) must not displace a 0.7 answer from the model.
            merged = dict(answers)
            replaced = False
            for key, judgment in alt.items():
                if key in merged and judgment.confidence > merged[key].confidence:
                    merged[key] = judgment
                    replaced = True
            if replaced:
                self.fallbacks += 1
            return merged
        return answers

    def health(self) -> ProviderHealth:
        h = self._primary.health()
        return ProviderHealth(
            name=f"fallback({h.name})",
            available=True,  # a fallback chain is always available; that is its point
            detail=f"{self.fallbacks} fallback(s); {h.detail}",
            calls=h.calls,
            failures=h.failures,
        )
