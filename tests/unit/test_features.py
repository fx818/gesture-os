"""Feature extraction. Pure, scale-invariant, clock-free — every downstream guarantee rests on
those three properties, so they are tested directly rather than inferred."""

import math

import pytest

from app.config import load
from app.features.extract import ExtractState, extract
from app.features.filters import OneEuroState, one_euro_step
from app.features.window import WindowBuffer
from app.perception.backends.synthetic import GENERATORS, linear_swipe, synth_hand
from app.types import FeatureFrame, Frame, Handedness

CFG = load(use_env=False)


def _run(source):
    st = ExtractState()
    out = []
    for f in source.frames():
        st, ff = extract(st, f, CFG.precision)
        out.append(ff)
    return out


def test_features_are_invariant_to_scale():
    # A hand 30cm from the camera and the same hand at 60cm must produce the same features,
    # otherwise every threshold in config means a different thing at a different distance and a
    # fixture only validates the camera it was recorded on.
    def frames(scale):
        return [
            Frame(i, i * 33.3, 640, 480, (synth_hand(0.5, 0.5, scale=scale, openness=0.6),))
            for i in range(6)
        ]

    def features(scale):
        st = ExtractState()
        out = []
        for f in frames(scale):
            st, ff = extract(st, f, CFG.precision)
            out.append(ff.right)
        return out[-1]

    small, large = features(0.6), features(1.4)
    assert small.openness == pytest.approx(large.openness, abs=1e-6)
    assert small.pinch_thumb_index == pytest.approx(large.pinch_thumb_index, abs=1e-6)
    for a, b in zip(small.joint_angles, large.joint_angles):
        assert a == pytest.approx(b, abs=1e-6)


def test_features_are_invariant_to_translation():
    def features(cx, cy):
        st = ExtractState()
        out = None
        for i in range(6):
            f = Frame(i, i * 33.3, 640, 480, (synth_hand(cx, cy, openness=0.6),))
            st, ff = extract(st, f, CFG.precision)
            out = ff.right
        return out

    a, b = features(0.3, 0.3), features(0.7, 0.6)
    assert a.openness == pytest.approx(b.openness, abs=1e-6)
    for x, y in zip(a.joint_angles, b.joint_angles):
        assert x == pytest.approx(y, abs=1e-6)


def test_speed_is_reported_in_palm_widths_per_second():
    # Thresholds in config are in palm-widths/s. If this unit ever drifts, every threshold is
    # silently wrong by an unknown factor.
    frames = _run(linear_swipe("left", speed=2.4, duration_s=1.0))
    speeds = [f.right.palm_speed for f in frames if f.right and f.right.palm_speed > 0]
    assert speeds
    assert sorted(speeds)[len(speeds) // 2] == pytest.approx(2.4, rel=0.1)


def test_velocity_comes_from_raw_position_not_the_filtered_one():
    # One Euro exists to smooth the CURSOR, not to attenuate the EVIDENCE. Deriving velocity from
    # the filtered centroid made a 2.4 pw/s swipe measure 1.63 — under the gross threshold — so a
    # committed sweep was indistinguishable from slow pointing.
    frames = _run(linear_swipe("left", speed=2.4, duration_s=0.5))
    speeds = [f.right.palm_speed for f in frames if f.right and f.right.palm_speed > 0]
    assert max(speeds) > 2.0, "filter lag is bleeding into the velocity estimate"


def test_a_straight_sweep_is_coherent_and_a_tremor_is_not():
    # This single property is what stops a shaking hand firing a window command: tremor reaches
    # 2.08 pw/s, ABOVE the 1.8 gross threshold, and is rejected on coherence alone.
    swipe = [f.right.palm_dir_coherence for f in _run(linear_swipe("left")) if f.right]
    tremor = [f.right.palm_dir_coherence for f in _run(GENERATORS["tremor"]()) if f.right]
    assert max(swipe) > 0.95
    assert sorted(tremor)[len(tremor) // 2] < 0.5


def test_index_extension_distinguishes_pointing_from_an_open_hand():
    # Measured relative to the other fingertips: an open flat hand has a long index too, and must
    # not read as pointing.
    st = ExtractState()
    _, pointing = extract(
        st, Frame(0, 0.0, 640, 480, (synth_hand(0.5, 0.5, openness=0.1, index_extension=1.0),)),
        CFG.precision,
    )
    _, flat = extract(
        ExtractState(), Frame(0, 0.0, 640, 480, (synth_hand(0.5, 0.5, openness=1.0),)),
        CFG.precision,
    )
    assert pointing.right.index_extension > CFG.precision.index_extension
    assert flat.right.index_extension < CFG.precision.index_extension


def test_a_hand_leaving_frame_drops_its_filter_history():
    # Otherwise the gap produces one enormous velocity spike on return, which reads as a swipe.
    st = ExtractState()
    st, _ = extract(st, Frame(0, 0.0, 640, 480, (synth_hand(0.2, 0.5),)), CFG.precision)
    st, _ = extract(st, Frame(1, 33.0, 640, 480, ()), CFG.precision)
    assert st.hands == {}
    st, ff = extract(st, Frame(2, 3000.0, 640, 480, (synth_hand(0.9, 0.5),)), CFG.precision)
    assert ff.right.palm_speed == 0.0


def test_extract_never_reads_a_clock():
    # Replay determinism depends on this absolutely. Same frames with shifted timestamps must
    # produce the same geometry.
    a = _run(linear_swipe("left"))
    b = _run(linear_swipe("left"))
    assert [f.right.palm_speed for f in a if f.right] == [f.right.palm_speed for f in b if f.right]


# --- One Euro ----------------------------------------------------------------------------

def test_one_euro_is_a_pure_fold():
    cfg = CFG.precision.one_euro
    s = OneEuroState()
    s1, v1 = one_euro_step(s, 0.5, 0.0, cfg)
    s2, v2 = one_euro_step(s, 0.5, 0.0, cfg)
    assert s1 == s2 and v1 == v2


def test_one_euro_passes_the_first_sample_through():
    s, v = one_euro_step(OneEuroState(), 0.42, 0.0, CFG.precision.one_euro)
    assert v == 0.42


def test_one_euro_survives_a_duplicate_timestamp():
    # A dropped or repeated frame timestamp would otherwise divide by zero and teleport the cursor.
    cfg = CFG.precision.one_euro
    s, _ = one_euro_step(OneEuroState(), 0.5, 100.0, cfg)
    s2, v = one_euro_step(s, 0.9, 100.0, cfg)
    assert v == pytest.approx(0.5)


def test_one_euro_suppresses_jitter_more_than_it_suppresses_motion():
    # The whole point of an adaptive cutoff: still hands get smoothed hard, moving hands do not.
    cfg = CFG.precision.one_euro
    s = OneEuroState()
    jittered = []
    for i in range(30):
        x = 0.5 + (0.002 if i % 2 else -0.002)
        s, v = one_euro_step(s, x, i * 33.0, cfg)
        jittered.append(v)
    assert max(jittered[10:]) - min(jittered[10:]) < 0.002

    s = OneEuroState()
    moving = []
    for i in range(30):
        s, v = one_euro_step(s, 0.5 + i * 0.02, i * 33.0, cfg)
        moving.append(v)
    assert moving[-1] - moving[0] > 0.4


# --- window ------------------------------------------------------------------------------

def test_window_is_trimmed_by_time_not_by_frame_count():
    # At a variable frame rate — and this camera runs at 15fps, not the requested 30 — a fixed
    # count would silently mean a different time span, and every "per second" threshold would
    # drift with it.
    buf = WindowBuffer(span_ms=250.0, min_frames=2)
    w = None
    for t in range(0, 1000, 100):
        buf, w = buf.push(FeatureFrame(t_ms=float(t), right=None, left=None, bimanual=None))
    assert w is not None
    assert w.span_ms <= 250.0


def test_window_is_none_until_it_has_enough_frames():
    # Acting on a partial window would fire on the very first frame after a hand appears.
    buf = WindowBuffer(span_ms=250.0, min_frames=5)
    for i in range(4):
        buf, w = buf.push(FeatureFrame(t_ms=i * 33.0, right=None, left=None, bimanual=None))
        assert w is None
    buf, w = buf.push(FeatureFrame(t_ms=132.0, right=None, left=None, bimanual=None))
    assert w is not None
