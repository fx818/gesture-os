"""The one and only module allowed to import `typesafe_sdk`.

Enforced by `.importlinter` — every other module speaks the vocabulary in `decision/questions.py`
and `decision/provider.py`, so swapping or mocking the judgment backend touches one file.

Two corrections to the published documentation, both verified against typesafe-sdk 0.6.0 and both
of which produce broken code if taken on faith:

  * Answers come back on a single `response.answers[key]` mapping, NOT on separate
    `.nouls` / `.choices` / `.scores` attributes.
  * `NoulAnswer` carries only `noul: float`. There is **no** `confidence` field on a Noul, though
    the docs describe confidence on every answer. We derive one in `provider.noul_confidence`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping

from typesafe_sdk import (
    Choice,
    Noul,
    RetryPolicy,
    Score,
    TypeSafeAPIError,
    TypeSafeClient,
    TypeSafeError,
)

from app.decision.provider import (
    Judgment,
    JudgmentRequest,
    ProviderError,
    ProviderHealth,
    Source,
    noul_confidence,
)
from app.decision.questions import ChoiceQ, NoulQ, Question, ScoreQ
from app.decision.sanitize import sanitize_state


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    latency_ms: float
    detail: str


def probe() -> ProbeResult:
    """One minimal round trip, for `doctor --jev`.

    Measures real RTT from this machine, which is the number that decides whether a judgment point
    can sit inside a dwell window or must be batched offline. See ADR-0004 — measured p50 here is
    ~375 ms, not the documented 150 ms.
    """
    t0 = time.monotonic()
    try:
        with TypeSafeClient() as client:
            client.system_one(
                state={"probe": "a terminal window"},
                questions={"ok": Noul(instructions="This describes a terminal.")},
            )
    except ImportError:
        return ProbeResult(False, 0.0, "typesafe-sdk not installed")
    except Exception as e:  # noqa: BLE001 — doctor reports, it does not handle
        return ProbeResult(False, (time.monotonic() - t0) * 1000, f"{type(e).__name__}: {e}")
    return ProbeResult(True, (time.monotonic() - t0) * 1000, "")


def _to_sdk(q: Question):
    if isinstance(q, ChoiceQ):
        return Choice(instructions=q.instructions, criteria=dict(q.options))
    if isinstance(q, ScoreQ):
        return Score(instructions=q.instructions, criteria=list(q.levels))
    if isinstance(q, NoulQ):
        if q.when_true or q.when_false:
            return Noul(
                instructions=q.instructions,
                criteria={"true": q.when_true or "", "false": q.when_false or ""},
            )
        return Noul(instructions=q.instructions)
    raise ProviderError(f"unsupported question type {type(q).__name__}")


def _from_sdk(key: str, answer, latency_ms: float) -> Judgment:
    """Normalize the three answer shapes into one Judgment."""
    if hasattr(answer, "choice"):
        return Judgment(
            key=key,
            value=answer.choice,
            confidence=float(answer.confidence),
            source=Source.JEV,
            probabilities=dict(answer.probabilities or {}),
            latency_ms=latency_ms,
        )
    if hasattr(answer, "score"):
        return Judgment(
            key=key,
            value=float(answer.score),
            confidence=float(answer.confidence),
            source=Source.JEV,
            probabilities={str(k): float(v) for k, v in (answer.probabilities or {}).items()},
            latency_ms=latency_ms,
        )
    if hasattr(answer, "noul"):
        value = float(answer.noul)
        return Judgment(
            key=key,
            value=value,
            confidence=noul_confidence(value),
            source=Source.JEV,
            latency_ms=latency_ms,
        )
    raise ProviderError(f"unrecognised answer shape for {key!r}: {type(answer).__name__}")


class TypeSafeProvider:
    """Live Jev. One call carries every question for a point — speculative fan-out, evaluated in
    parallel for one round trip, and output tokens are free so extra questions are nearly free."""

    def __init__(
        self,
        *,
        client: TypeSafeClient | None = None,
        timeout_s: float = 2.0,
        max_retries: int = 2,
        max_state_chars: int = 4000,
    ) -> None:
        self._client = client or TypeSafeClient()
        self._retry = RetryPolicy(max_retries=max_retries, timeout=timeout_s)
        self._timeout = timeout_s
        self._max_state_chars = max_state_chars
        self._calls = 0
        self._failures = 0
        self._last_error = ""

    def judge(self, req: JudgmentRequest) -> Mapping[str, Judgment]:
        self._calls += 1
        state = sanitize_state(req.state, max_total_chars=self._max_state_chars)
        questions = {k: _to_sdk(q) for k, q in req.questions.items()}

        t0 = time.monotonic()
        try:
            response = self._client.system_one(
                state, questions, retry=self._retry, timeout=self._timeout
            )
        except (TypeSafeAPIError, TypeSafeError) as e:
            self._failures += 1
            self._last_error = f"{type(e).__name__}: {e}"
            raise ProviderError(self._last_error) from e
        except Exception as e:  # noqa: BLE001 — never let a transport bug reach the caller raw
            self._failures += 1
            self._last_error = f"{type(e).__name__}: {e}"
            raise ProviderError(self._last_error) from e

        latency_ms = (time.monotonic() - t0) * 1000
        answers = response.answers
        missing = set(req.questions) - set(answers)
        if missing:
            raise ProviderError(f"response omitted question(s): {sorted(missing)}")
        return {k: _from_sdk(k, answers[k], latency_ms) for k in req.questions}

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            name="jev",
            available=self._failures == 0 or self._calls > self._failures,
            detail=self._last_error,
            calls=self._calls,
            failures=self._failures,
        )

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
