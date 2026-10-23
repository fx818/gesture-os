# ADR-0001 — Jev is never on the per-frame path

**Status:** accepted · 2026-09-17

## Context

TypeSafe's Jev is a text-only System One classifier: ~150 ms per call, 1200 req/min, $0.042 per
million input tokens. It generates nothing — it picks, scores, or judges.

At 30 fps a per-frame call would be 30 req/s against a 20 req/s ceiling, roughly $55/day/user at
~500 tokens of serialized landmarks per frame, and 150 ms of network latency inside a 50 ms cursor
budget. It would also send the contents of the camera feed off the machine, contradicting the scope
doc's explicit "fully on-device, no frames leave the machine".

Jev also cannot do the work: the documented weaknesses include counting, arithmetic and treating
dates as ordered quantities. The feature layer is *entirely* arithmetic.

## Decision

The arbitration engine stays local, numeric and pure. Jev fires only on discrete events — focus
changed, menu summoned, recording finished, panic pressed, config time.

Enforced by four independent barriers rather than by discipline:

1. `.importlinter` forbids `app.arbitration -> app.decision` (and httpx/requests/typesafe_sdk).
2. `JudgmentBroker` owns the only thread permitted to call a provider; the frame loop calls a
   non-blocking `drain()`.
3. `DecisionContext` is a frozen **input** to `step()`. It carries `app_class_age_ms` so a guard
   can distrust a stale answer, but there is no path from the engine to a request.
4. A CI test asserts `broker.calls_from_loop_thread == 0`.

## Consequences

Jev being down, rate-limited, unkeyed or slow degrades one feature's quality and never the
product's availability. `--offline` swaps in a rules provider behind the same interface, and every
test in `make ci` runs on that path.

Cost at the real call rate — roughly 200 focus changes/day, cached per app — is under $0.01/day.
