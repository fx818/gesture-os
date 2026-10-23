"""types.py is the contract every layer agrees on, so its guards must actually fire."""

import pytest

from app.types import (
    AppClass,
    DecisionContext,
    FeatureFrame,
    FeatureWindow,
    Frame,
    Hand,
    Handedness,
    Landmark,
    LANDMARK_COUNT,
)


def _hand(handedness=Handedness.RIGHT, score=0.9):
    return Hand(handedness, score, tuple((i / 21, i / 42, 0.0) for i in range(LANDMARK_COUNT)))


def test_hand_rejects_wrong_landmark_count():
    # A truncated hand from a partial detection must fail loudly at the boundary rather than
    # produce silently wrong features 3 layers downstream.
    with pytest.raises(ValueError):
        Hand(Handedness.LEFT, 1.0, ((0.0, 0.0, 0.0),))


def test_landmark_enum_indexes_into_the_tuple():
    # Feature code reads anatomy, not magic indices; this is the mapping it relies on.
    h = _hand()
    assert h.at(Landmark.WRIST) == h.landmarks[0]
    assert h.at(Landmark.INDEX_TIP) == h.landmarks[8]
    assert h.at(Landmark.PINKY_TIP) == h.landmarks[20]


def test_frame_hand_lookup_returns_none_when_absent():
    # Absence of a hand is a signal the arbiter acts on (decay to Idle), not an error case.
    f = Frame(0, 0.0, 1280, 720, (_hand(Handedness.RIGHT),))
    assert f.hand(Handedness.RIGHT) is not None
    assert f.hand(Handedness.LEFT) is None


def test_empty_feature_window_is_rejected():
    # Guards index .latest unconditionally; an empty window would be an IndexError deep in a
    # predicate rather than a clear failure at construction.
    with pytest.raises(ValueError):
        FeatureWindow(())


def test_feature_window_span_is_measured_from_frame_time_not_a_clock():
    # Replay determinism depends on span coming from data. If this ever reads a real clock,
    # golden intent streams stop reproducing.
    frames = tuple(FeatureFrame(t_ms=float(t), right=None, left=None, bimanual=None)
                   for t in (100, 133, 166, 200))
    w = FeatureWindow(frames)
    assert w.span_ms == 100.0
    assert w.t_end == 200.0
    assert len(w) == 4


def test_feature_frame_present_is_false_only_when_both_hands_missing():
    assert FeatureFrame(0.0, None, None, None).present is False


def test_empty_decision_context_is_maximally_distrustful():
    # A context that has never heard from Jev must look stale and unconfident, so that any guard
    # gating on app_class declines rather than acting on a default.
    ctx = DecisionContext.empty()
    assert ctx.app_class is AppClass.UNKNOWN
    assert ctx.app_class_confidence == 0.0
    assert ctx.app_class_age_ms == float("inf")
    assert ctx.focus is None
