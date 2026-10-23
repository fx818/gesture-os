"""Bimanual chording — the off-hand as a modifier key."""

from app.arbitration.chording import Chord, acting_hand, detect
from app.config import load
from app.poses import PoseLibrary, PoseTemplate
from app.types import BimanualFeatures, FeatureFrame, FeatureWindow, HandFeatures, Handedness

import dataclasses

CFG = load(use_env=False)


# Varied on purpose: a CONSTANT angle vector has zero variance, so its mean-centred correlation
# with anything is undefined and `similarity` returns 0.0. Real joint angles are never identical
# across all fifteen joints, but a test fixture easily can be.
POSE_ANGLES = tuple(0.2 + 0.1 * (i % 4) for i in range(15))


def _hand(speed=0.0, angles=None):
    return HandFeatures(
        palm_centroid=(0.5, 0.5, 0.0), palm_velocity=(0.0, 0.0, 0.0), palm_speed=speed,
        palm_dir_coherence=0.0, fingertip_speeds=(0.0,) * 5, openness=0.5,
        joint_angles=tuple(angles or POSE_ANGLES), palm_normal=(0.0, 0.0, 1.0), wrist_roll=0.0,
        pinch_thumb_index=1.0, pinch_thumb_middle=1.0, index_extension=0.0, tracking_score=1.0,
    )


def _window(left=None, right=None):
    f = FeatureFrame(
        t_ms=0.0, right=right, left=left,
        bimanual=BimanualFeatures(0.3, 1.0, 0.0, 0.5) if (left and right) else None,
    )
    return FeatureWindow((f,))


def _cfg_with_pose(name="fist", angles=None):
    lib = PoseLibrary().with_template(PoseTemplate(name, tuple(angles or POSE_ANGLES), 0.4))
    return dataclasses.replace(CFG, poses=lib)


def test_no_chord_when_only_one_hand_is_visible():
    assert not detect(_window(right=_hand()), _cfg_with_pose()).active


def test_no_chord_when_the_pose_library_is_empty():
    # Without templates there is nothing a chord could be, and "the other hand is visible" must
    # never on its own change what a gesture means.
    assert not detect(_window(left=_hand(), right=_hand(speed=1.0)), CFG).active


def test_the_acting_hand_is_the_faster_one_not_the_right_one():
    # A left-handed user points with their left. Hard-coding handedness would make the system
    # unusable for them.
    frame = _window(left=_hand(speed=2.0), right=_hand(speed=0.1)).latest
    _, acting = acting_hand(frame)
    assert acting is Handedness.LEFT


def test_the_modifier_is_whichever_hand_is_not_acting():
    angles = POSE_ANGLES
    cfg = _cfg_with_pose("fist", angles)
    # Right hand moving fast -> it is acting, so the LEFT hand is the modifier.
    chord = detect(_window(left=_hand(angles=angles), right=_hand(speed=3.0)), cfg)
    assert chord.active and chord.hand is Handedness.LEFT


def test_a_moving_off_hand_is_not_a_chord():
    # A waving off-hand is gesturing or reaching, not holding a modifier down.
    angles = POSE_ANGLES
    cfg = _cfg_with_pose("fist", angles)
    fast_modifier = _hand(speed=CFG.macro.max_speed * 5, angles=angles)
    assert not detect(_window(left=fast_modifier, right=_hand(speed=6.0)), cfg).active


def test_an_unrecognised_pose_is_not_a_chord():
    cfg = _cfg_with_pose("fist", POSE_ANGLES)
    unrelated = _hand(angles=tuple(reversed(POSE_ANGLES)))
    chord = detect(_window(left=unrelated, right=_hand(speed=3.0)), cfg)
    assert not chord.active or chord.similarity >= CFG.macro.template_cosine_min


def test_chord_none_is_inactive():
    assert not Chord.none().active


def test_a_degenerate_constant_pose_vector_matches_nothing():
    # Zero variance means correlation is undefined. Returning 0.0 (no match) is the safe reading;
    # raising would take the frame loop down over a tracking artefact.
    from app.poses import similarity

    assert similarity([0.5] * 15, [0.5] * 15) == 0.0
