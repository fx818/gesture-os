"""PointerSink contract. Parametrized so the uinput backend joins it later under -m hardware.

The panic properties here are the ones that matter: the scope doc makes the kill switch a hard
guarantee, and a PointerSink that can't be released is a stuck mouse button on a real desktop.
"""

import pytest

from app.effectors.backends import null, recording
from app.intents import Button


def _sinks():
    return [null.NullPointerSink(), recording.RecordingPointerSink(recording.Journal())]


@pytest.mark.parametrize("sink", _sinks(), ids=lambda s: type(s).__name__)
def test_release_all_is_idempotent(sink):
    # The watchdog may fire repeatedly while a guard stays true. Releasing twice must be safe.
    sink.release_all()
    sink.release_all()
    sink.release_all()


@pytest.mark.parametrize("sink", _sinks(), ids=lambda s: type(s).__name__)
def test_release_all_works_without_any_prior_press(sink):
    # Panic can fire before anything was ever pressed — e.g. straight out of Idle.
    sink.release_all()


@pytest.mark.parametrize("sink", _sinks(), ids=lambda s: type(s).__name__)
def test_motion_accepts_fractional_deltas(sink):
    # Features are normalized floats; a sink that demanded ints would push rounding up into the
    # pure layer, where accumulating the remainder across frames belongs in the backend instead.
    sink.move_rel(0.4, -0.4)
    sink.move_rel(1e-3, 0.0)


@pytest.mark.parametrize("sink", _sinks(), ids=lambda s: type(s).__name__)
def test_button_down_and_up_are_separate_calls(sink):
    # Drag needs a press that outlives the frame that started it, so button() takes an explicit
    # down flag rather than exposing a click() that couples press to release.
    sink.button(Button.LEFT, True)
    sink.button(Button.LEFT, False)


def test_recording_sink_preserves_call_order():
    j = recording.Journal()
    s = recording.RecordingPointerSink(j)
    s.button(Button.LEFT, True)
    s.move_rel(2.0, 0.0)
    s.button(Button.LEFT, False)
    assert j.methods() == ["button", "move_rel", "button"]


def test_recording_sinks_share_one_ordered_transcript():
    # Golden-stream comparisons need a single interleaved log across pointer and keys, not two
    # separate ones that have to be merged by timestamp afterwards.
    j = recording.Journal()
    p, k = recording.RecordingPointerSink(j), recording.RecordingKeySink(j)
    p.move_rel(1.0, 1.0)
    k.chord(("super", "left"))
    p.button(Button.LEFT, True)
    assert j.methods() == ["move_rel", "chord", "button"]
