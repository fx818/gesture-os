"""Hysteresis properties, over generated input rather than fixed fixtures.

The scope doc's #1 listed risk is false positives at scale. A fixture proves one path; these prove
the invariant across a range of speeds, noise levels and frame rates — including the awkward ones
nobody thinks to record.
"""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.arbitration.engine import step
from app.arbitration.modes import default_registry
from app.arbitration.state import ArbiterState
from app.config import load
from app.features.extract import ExtractState, extract
from app.features.window import WindowBuffer
from app.perception.backends.synthetic import hover_at_threshold, linear_swipe, rest
from app.types import DecisionContext, ModeId

CFG = load(use_env=False)
REGISTRY = default_registry()
CTX = DecisionContext.empty()


def drive(source):
    """Run a source through features + arbiter, returning the transition list."""
    es = ExtractState()
    buf = WindowBuffer(
        span_ms=CFG.arbitration.window_span_ms, min_frames=CFG.arbitration.window_min_frames
    )
    state = ArbiterState()
    transitions = []
    for frame in source.frames():
        es, ff = extract(es, frame, CFG.precision)
        buf, w = buf.push(ff)
        if w is None:
            continue
        out = step(state, w, CTX, REGISTRY, CFG)
        if out.state.mode is not state.mode:
            transitions.append((w.t_end, out.state.mode))
        state = out.state
    return transitions


@settings(max_examples=25, deadline=None)
@given(speed=st.floats(min_value=1.5, max_value=2.2), noise=st.floats(min_value=0.0, max_value=0.15))
def test_velocity_parked_near_the_gross_threshold_never_flickers(speed, noise):
    # The property the four-layer stack exists for. Anywhere in the band around the threshold,
    # with any plausible noise, the engine must not oscillate.
    transitions = drive(hover_at_threshold(duration_s=3.0, speed=speed, noise=noise))
    assert len(transitions) <= 1, f"speed={speed:.2f} noise={noise:.2f} -> {transitions}"


@settings(max_examples=20, deadline=None)
@given(jitter=st.floats(min_value=0.0, max_value=0.004))
def test_a_resting_hand_never_engages_at_any_plausible_jitter(jitter):
    assert drive(rest(duration_s=3.0, jitter=jitter)) == []


@settings(max_examples=20, deadline=None)
@given(speed=st.floats(min_value=2.2, max_value=6.0))
def test_a_committed_sweep_always_fires_once(speed):
    # The other side of the same coin: hysteresis must not make real gestures unreachable.
    transitions = drive(linear_swipe("left", speed=speed, duration_s=1.0))
    gross = [m for _, m in transitions if m is ModeId.GROSS]
    assert len(gross) == 1, f"speed={speed:.2f} -> {[m.value for _, m in transitions]}"


@settings(max_examples=15, deadline=None)
@given(fps=st.sampled_from([12.0, 15.0, 24.0, 30.0, 60.0]))
def test_behaviour_is_frame_rate_independent(fps):
    # This camera delivers 15fps, not the 30 it advertises (ADR-0006), and a different machine
    # will differ again. Thresholds are per-second, the window is trimmed by time, and dwell is
    # measured in milliseconds — so the same gesture must resolve the same way at any rate.
    transitions = drive(linear_swipe("left", speed=3.0, duration_s=1.0, fps=fps))
    assert [m for _, m in transitions] == [ModeId.GROSS], f"fps={fps} -> {transitions}"


@settings(max_examples=15, deadline=None)
@given(
    speed=st.floats(min_value=0.05, max_value=0.5),
    jitter=st.floats(min_value=0.0, max_value=0.003),
)
def test_slow_motion_never_reaches_gross(speed, jitter):
    from app.perception.backends.synthetic import precision_trace

    transitions = drive(precision_trace(duration_s=2.0, speed=speed, jitter=jitter))
    assert ModeId.GROSS not in [m for _, m in transitions]


def test_transitions_are_never_faster_than_the_minimum_dwell():
    # Layer 3 of the stack, asserted directly rather than inferred from a fixture.
    transitions = drive(hover_at_threshold(duration_s=5.0, speed=1.9, noise=0.12))
    for (t0, m0), (t1, _m1) in zip(transitions, transitions[1:]):
        assume(CFG.arbitration.min_dwell_ms[m0] > 0)
        assert t1 - t0 >= CFG.arbitration.min_dwell_ms[m0]
