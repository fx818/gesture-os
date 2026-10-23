"""Pose template library. Per-user by design — hand proportions vary enough that a shipped
'fist' would be worse than none."""

import pytest

from app.poses import JOINT_ANGLE_COUNT, PoseLibrary, PoseTemplate, average, cosine

A = tuple(0.1 * i for i in range(JOINT_ANGLE_COUNT))
B = tuple(reversed(A))


def test_a_template_must_have_the_right_number_of_angles():
    with pytest.raises(ValueError):
        PoseTemplate("bad", (0.1, 0.2), 0.5)


def test_cosine_is_one_for_identical_poses_and_lower_for_different_ones():
    assert cosine(A, A) == pytest.approx(1.0)
    assert cosine(A, B) < cosine(A, A)


def test_cosine_is_clamped_and_safe_on_degenerate_input():
    zeros = tuple(0.0 for _ in range(JOINT_ANGLE_COUNT))
    assert cosine(A, zeros) == 0.0
    assert cosine(A, (0.1, 0.2)) == 0.0  # length mismatch, not a crash
    assert 0.0 <= cosine(A, B) <= 1.0


def test_library_is_empty_by_default_so_macro_falls_back_rather_than_misfiring():
    # If this ever ships non-empty, macro starts matching MY idea of a fist against a stranger's
    # hand, which is worse than the honest fallback.
    assert PoseLibrary().is_empty


def test_re_recording_a_pose_replaces_it_rather_than_competing_with_it():
    lib = PoseLibrary().with_template(PoseTemplate("fist", A, 0.2))
    lib = lib.with_template(PoseTemplate("fist", B, 0.3))
    assert len(lib.templates) == 1
    assert lib.get("fist").angles == B


def test_best_returns_the_closest_template():
    lib = PoseLibrary().with_template(PoseTemplate("a", A, 0.1)).with_template(
        PoseTemplate("b", B, 0.1)
    )
    assert lib.best(A).name == "a"
    assert lib.best(B).name == "b"


def test_best_on_an_empty_library_matches_nothing():
    # -1.0, not 0.0: the metric is a correlation whose range is -1..1, and 0.0 is a real score
    # meaning "unrelated" rather than "no match at all".
    m = PoseLibrary().best(A)
    assert not m.matched and m.similarity == -1.0


def test_averaging_smooths_tracking_noise():
    # A template from one frame encodes that frame's noise and then matches the noise as much as
    # the pose.
    noisy = [tuple(a + (0.01 if i % 2 else -0.01) for a in A) for i in range(6)]
    t = average("fist", noisy, [0.2] * 6)
    assert t.samples == 6
    for got, want in zip(t.angles, A):
        assert got == pytest.approx(want, abs=1e-9)


def test_library_round_trips_through_disk(tmp_path):
    path = tmp_path / "poses.json"
    PoseLibrary().with_template(PoseTemplate("fist", A, 0.25, 7, "note")).save(path)
    back = PoseLibrary.load(path)
    assert back.get("fist").samples == 7
    assert back.get("fist").openness == pytest.approx(0.25)


def test_loading_a_missing_library_yields_an_empty_one(tmp_path):
    assert PoseLibrary.load(tmp_path / "nope.json").is_empty
