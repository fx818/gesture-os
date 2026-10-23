"""The arbitration engine — the core deliverable.

Every expectation here is a sentence from docs/scope.md turned into an assertion. The negatives
matter more than the positives: anyone can make a swipe fire, and the thresholds are set by what
must NOT fire.
"""

import pytest

from app.arbitration.engine import step
from app.arbitration.modes import default_registry
from app.arbitration.registry import DuplicateMode, ModeRegistry, ModeSpec
from app.arbitration.state import ArbiterState
from app.config import load
from app.effectors.backends import recording
from app.effectors.ports import EffectorSet
from app.perception.ndjson import FileLandmarkSource
from app.runtime import golden
from app.runtime.pipeline import run_pipeline
from app.types import DecisionContext, ModeId

CFG = load(use_env=False)


def replay(name: str):
    journal = recording.Journal()
    fx = EffectorSet(
        pointer=recording.RecordingPointerSink(journal),
        keys=recording.RecordingKeySink(journal),
    )
    return run_pipeline(FileLandmarkSource(golden.SESSIONS / f"{name}.ndjson.gz"), fx, cfg=CFG)


def modes(result):
    return [m.value for _, m in result.transitions]


def kinds(result):
    out: dict[str, int] = {}
    for e in result.intents:
        out[e.intent.kind] = out.get(e.intent.kind, 0) + 1
    return out


# --- negatives: the real specification ---------------------------------------------------

@pytest.mark.parametrize(
    "fixture",
    ["rest-60s", "coffee-cup", "hover-at-threshold", "live-desk-6s"],
)
def test_negative_fixtures_emit_nothing_at_all(fixture):
    r = replay(fixture)
    assert r.transitions == [], f"{fixture} changed mode: {modes(r)}"
    assert r.intents == [], f"{fixture} emitted {kinds(r)}"


def test_a_relaxed_hand_at_rest_never_engages():
    # The scope doc's escape hatch: "reaching for a coffee cup decays back to Idle instead of being
    # force-fit into a command". 60 seconds, 1800 frames, zero events.
    r = replay("rest-60s")
    assert r.frames == 1800
    assert modes(r) == []


def test_velocity_parked_on_the_gross_threshold_does_not_oscillate():
    # The hysteresis torture test. A single-threshold design flips in and out of GROSS dozens of
    # times here; the four-layer stack must produce at most one transition.
    r = replay("hover-at-threshold")
    assert len(r.transitions) <= 1, f"flickered: {modes(r)}"


# --- positives ---------------------------------------------------------------------------

def test_slow_pointing_enters_precision_and_stays_there():
    r = replay("precision-trace")
    assert modes(r) == ["precision"]
    assert kinds(r)["MoveCursor"] > 0


def test_one_pinch_produces_exactly_one_press_and_one_release():
    # A single-threshold pinch chatters; this measured 5 button events before the Schmitt edge
    # detection went in. A stuck or doubled mouse button is among the worst failures available.
    r = replay("pinch-clicks")
    assert kinds(r)["ButtonPress"] == 2


def test_one_swipe_produces_exactly_one_window_switch():
    # Emitting on every sustained frame turned one swipe into 18 switches. One deliberate sweep
    # must mean exactly one command, or the gesture is unusable regardless of what it is bound to.
    for fixture, direction in (("swipe-left", "left"), ("swipe-right", "right")):
        r = replay(fixture)
        assert modes(r) == ["gross"], fixture
        assert kinds(r) == {"SwitchWindow": 1}, fixture
        assert r.intents[0].intent.direction.value == direction


def test_a_held_pose_enters_macro_after_its_dwell():
    r = replay("pose-hold")
    assert "macro" in modes(r)
    entered_at = next(t for t, m in r.transitions if m is ModeId.MACRO)
    assert entered_at >= CFG.arbitration.hold_ms[ModeId.MACRO]


def test_both_palms_open_and_still_trigger_panic_exactly_once():
    # The kill switch. It must fire, and it must not re-fire while the pose is held — four
    # ReleaseAll intents came out before PANIC was made sticky.
    r = replay("two-hand-panic")
    assert modes(r) == ["panic"]
    assert kinds(r) == {"ReleaseAll": 1}


def test_a_tremoring_hand_still_gets_stable_cursor_control():
    # The accessibility case. High-amplitude tremor made the engine flip in and out of precision
    # nine times in four seconds until precision got a Schmitt speed pair. Per-user calibration
    # (P5) tightens this further; the default must already be usable.
    r = replay("tremor-high")
    assert len(r.transitions) == 1
    assert modes(r) == ["precision"]


# --- engine properties -------------------------------------------------------------------

def test_step_is_pure():
    # No I/O, no clock, no globals. Everything downstream — replay, golden files, calibration —
    # depends on this being true.
    registry = default_registry()
    ctx = DecisionContext.empty()
    fixture = golden.SESSIONS / "swipe-left.ndjson.gz"

    from app.features.extract import ExtractState, extract
    from app.features.window import WindowBuffer

    es = ExtractState()
    buf = WindowBuffer(
        span_ms=CFG.arbitration.window_span_ms, min_frames=CFG.arbitration.window_min_frames
    )
    windows = []
    for frame in FileLandmarkSource(fixture).frames():
        es, ff = extract(es, frame, CFG.precision)
        buf, w = buf.push(ff)
        if w is not None:
            windows.append(w)

    state = ArbiterState()
    for w in windows[:20]:
        a = step(state, w, ctx, registry, CFG)
        b = step(state, w, ctx, registry, CFG)
        assert a.state == b.state and a.intents == b.intents
        state = a.state


def test_registry_refuses_duplicate_priorities():
    # Two modes at the same priority make the challenger ordering non-deterministic, which would
    # make "which mode wins" depend on dict ordering.
    from app.arbitration.guards import always
    from app.arbitration.modes.idle import IDLE

    clash = ModeSpec(mode=ModeId.MACRO, priority=IDLE.priority, enter=always(), sustain=always())
    with pytest.raises(DuplicateMode, match="priority"):
        ModeRegistry.build([IDLE, clash])


def test_a_registry_can_be_built_with_a_subset_of_modes():
    # Modes are registered data, so a test can exercise the state machine in isolation without
    # monkeypatching or global mutation.
    from app.arbitration.modes.idle import IDLE
    from app.arbitration.modes.precision import PRECISION

    r = ModeRegistry.build([IDLE, PRECISION])
    assert set(r.specs) == {ModeId.IDLE, ModeId.PRECISION}


def test_idle_never_competes_as_a_challenger():
    # IDLE's enter guard is always(), so letting it compete meant it displaced every real mode the
    # moment min_dwell expired: 33 transitions on a steady pointing gesture.
    r = replay("precision-trace")
    assert modes(r).count("idle") == 0
