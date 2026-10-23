"""The independent panic detector.

The scope doc requires the kill switch to work "even mid-macro or mid-drag" and to be independent
of the arbitration engine's state. These tests exercise it with no engine present at all — which
is the point.
"""

from app.config import load
from app.effectors.backends import recording
from app.effectors.ports import EffectorSet
from app.runtime.watchdog import PanicWatchdog
from app.types import BimanualFeatures, FeatureFrame, HandFeatures

CFG = load(use_env=False).panic


def _hand(openness: float, speed: float) -> HandFeatures:
    return HandFeatures(
        palm_centroid=(0.5, 0.5, 0.0), palm_velocity=(0.0, 0.0, 0.0), palm_speed=speed,
        palm_dir_coherence=0.0, fingertip_speeds=(0.0,) * 5, openness=openness,
        joint_angles=(0.0,) * 15, palm_normal=(0.0, 0.0, 1.0), wrist_roll=0.0,
        pinch_thumb_index=1.0, pinch_thumb_middle=1.0, index_extension=0.0, tracking_score=1.0,
    )


def _frame(t_ms: float, openness: float = 1.0, speed: float = 0.0, two_hands: bool = True):
    h = _hand(openness, speed)
    return FeatureFrame(
        t_ms=t_ms, right=h, left=h if two_hands else None,
        bimanual=BimanualFeatures(0.3, 1.0, 0.0, openness) if two_hands else None,
    )


def _wd():
    j = recording.Journal()
    fx = EffectorSet(
        pointer=recording.RecordingPointerSink(j), keys=recording.RecordingKeySink(j)
    )
    return PanicWatchdog(fx, CFG), j


def test_it_fires_after_the_pose_is_held_and_releases_every_sink():
    wd, journal = _wd()
    t = 0.0
    fired = False
    while t <= CFG.watchdog_hold_ms + 100 and not fired:
        fired = wd.observe(_frame(t))
        t += 33.0
    assert fired
    assert "pointer.release_all" in journal.methods()
    assert "keys.release_all" in journal.methods()


def test_it_does_not_fire_before_the_hold_elapses():
    # Otherwise any momentary two-palm pose — mid-gesture, mid-stretch — kills the session.
    wd, _ = _wd()
    assert not wd.observe(_frame(0.0))
    assert not wd.observe(_frame(CFG.watchdog_hold_ms / 2))


def test_it_fires_once_per_hold_not_once_per_frame():
    wd, journal = _wd()
    t, fires = 0.0, 0
    while t < CFG.watchdog_hold_ms * 4:
        fires += wd.observe(_frame(t))
        t += 33.0
    assert fires == 1


def test_releasing_the_pose_re_arms_it():
    # A kill switch with no way back is a trap: the user would have to restart the process.
    wd, _ = _wd()
    t = 0.0
    while t < CFG.watchdog_hold_ms * 2:
        wd.observe(_frame(t))
        t += 33.0
    assert wd.disengaged
    wd.observe(_frame(t, openness=0.0))
    assert not wd.disengaged


def test_one_hand_alone_never_triggers_it():
    wd, _ = _wd()
    t = 0.0
    fires = 0
    while t < CFG.watchdog_hold_ms * 3:
        fires += wd.observe(_frame(t, two_hands=False))
        t += 33.0
    assert fires == 0


def test_moving_hands_never_trigger_it():
    wd, _ = _wd()
    t, fires = 0.0, 0
    while t < CFG.watchdog_hold_ms * 3:
        fires += wd.observe(_frame(t, speed=CFG.max_speed * 5))
        t += 33.0
    assert fires == 0


def test_a_failing_effector_cannot_stop_it_or_raise():
    # It runs while the engine may be wedged and there is nothing above it to catch an exception.
    class Exploding:
        def capabilities(self):
            return frozenset()

        def release_all(self):
            raise RuntimeError("device gone")

        def close(self):
            pass

    j = recording.Journal()
    fx = EffectorSet(pointer=Exploding(), keys=recording.RecordingKeySink(j))
    wd = PanicWatchdog(fx, CFG)
    t, fired = 0.0, False
    while t <= CFG.watchdog_hold_ms + 100 and not fired:
        fired = wd.observe(_frame(t))
        t += 33.0
    assert fired
    assert "keys.release_all" in journal_methods(j)


def journal_methods(j):
    return j.methods()
