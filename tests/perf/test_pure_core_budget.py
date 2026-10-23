"""The pure core has its own latency budget, separate from perception.

Perception costs what the hardware costs (65ms sensor + 34ms inference on this machine, ADR-0006).
What must stay cheap is everything we control: feature extraction, the window, and `step`. If that
ever creeps, the two costs get conflated and the real regression hides behind the camera.

CPU only, no hardware, no network — stable enough to gate a CI run.
"""

import statistics
import time

from app.arbitration.engine import step
from app.arbitration.modes import default_registry
from app.arbitration.state import ArbiterState
from app.config import load
from app.features.extract import ExtractState, extract
from app.features.window import WindowBuffer
from app.perception.backends.synthetic import precision_trace
from app.types import DecisionContext

CFG = load(use_env=False)

# Generous against a 65ms frame interval, tight enough to catch an accidental O(n^2) in a guard.
BUDGET_P99_MS = 5.0


def test_features_plus_arbitration_stay_well_inside_the_frame_budget():
    frames = list(precision_trace(duration_s=4.0).frames())
    registry = default_registry()
    ctx = DecisionContext.empty()

    es = ExtractState()
    buf = WindowBuffer(
        span_ms=CFG.arbitration.window_span_ms, min_frames=CFG.arbitration.window_min_frames
    )
    state = ArbiterState()
    timings = []

    for frame in frames:
        t0 = time.perf_counter()
        es, ff = extract(es, frame, CFG.precision)
        buf, w = buf.push(ff)
        if w is not None:
            out = step(state, w, ctx, registry, CFG)
            state = out.state
        timings.append((time.perf_counter() - t0) * 1000.0)

    timings.sort()
    p99 = timings[min(len(timings) - 1, int(len(timings) * 0.99))]
    assert p99 < BUDGET_P99_MS, (
        f"pure core p99 is {p99:.2f}ms (p50 {statistics.median(timings):.2f}ms), "
        f"budget {BUDGET_P99_MS}ms"
    )
