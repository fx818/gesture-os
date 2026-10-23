"""Every effector backend must satisfy its port, honestly.

These run against the CI-safe backends (null, recording). The uinput / AT-SPI / shell-extension
backends join the same parametrize lists later under `-m hardware`, which is the point of writing
them as contract suites rather than per-backend tests.
"""

import pytest

from app.effectors.backends import null, recording
from app.effectors.ports import (
    EffectorSet,
    FocusSource,
    KeySink,
    OverlaySink,
    PointerSink,
    UiAutomationSource,
    WindowManager,
)
from app.types import Capability

_j = recording.Journal


def _pairs():
    return [
        (null.NullPointerSink(), PointerSink),
        (recording.RecordingPointerSink(_j()), PointerSink),
        (null.NullKeySink(), KeySink),
        (recording.RecordingKeySink(_j()), KeySink),
        (null.NullFocusSource(), FocusSource),
        (recording.RecordingFocusSource(_j()), FocusSource),
        (null.NullWindowManager(), WindowManager),
        (recording.RecordingWindowManager(_j()), WindowManager),
        (null.NullOverlaySink(), OverlaySink),
        (recording.RecordingOverlaySink(_j()), OverlaySink),
        (null.NullUiAutomationSource(), UiAutomationSource),
        (recording.RecordingUiAutomationSource(_j()), UiAutomationSource),
    ]


@pytest.mark.parametrize("backend,port", _pairs(), ids=lambda x: getattr(x, "__name__", type(x).__name__))
def test_backend_satisfies_its_port(backend, port):
    assert isinstance(backend, port)


@pytest.mark.parametrize("backend,port", _pairs(), ids=lambda x: getattr(x, "__name__", type(x).__name__))
def test_capabilities_are_a_frozenset_of_real_capabilities(backend, port):
    # The router does a subset check. A list, a set, or a bare string here would either silently
    # pass the check or explode at dispatch rather than at wiring.
    caps = backend.capabilities()
    assert isinstance(caps, frozenset)
    assert caps, f"{type(backend).__name__} declares no capabilities"
    assert all(isinstance(c, Capability) for c in caps)


def test_a_backend_may_declare_fewer_capabilities_than_its_port_suggests():
    # This is the mechanism the whole extension-deferral rests on: a WindowManager that can move
    # windows coarsely but cannot place arbitrary rectangles must be able to say so.
    coarse = null.NullWindowManager()
    full = null.NullWindowManager(null.WINDOW_FULL_CAPS)
    assert Capability.WINDOW_MOVE in coarse.capabilities()
    assert Capability.WINDOW_TILE_ARBITRARY not in coarse.capabilities()
    assert Capability.WINDOW_TILE_ARBITRARY in full.capabilities()


def test_effector_set_capabilities_are_the_union_of_its_members():
    s = EffectorSet(
        pointer=null.NullPointerSink(),
        keys=null.NullKeySink(),
        windows=null.NullWindowManager(null.WINDOW_FULL_CAPS),
    )
    caps = s.capabilities()
    assert Capability.POINTER_REL in caps
    assert Capability.KEY_SYNTH in caps
    assert Capability.WINDOW_TILE_ARBITRARY in caps
    assert Capability.OVERLAY not in caps  # no overlay backend wired


def test_effector_set_tolerates_absent_optional_backends():
    # A machine with no AT-SPI and no extension must still produce a usable set, not a crash.
    s = EffectorSet(pointer=null.NullPointerSink(), keys=null.NullKeySink())
    assert s.focus is None and s.windows is None
    assert len(s.all()) == 2
    s.close()


def test_effector_set_release_all_never_raises_even_when_a_sink_fails():
    # release_all runs from the watchdog while the engine may be wedged. There is nothing above
    # it to catch an exception, and one broken sink must not stop the others from releasing.
    class ExplodingPointer(null.NullPointerSink):
        def release_all(self):
            raise RuntimeError("device gone")

    j = recording.Journal()
    s = EffectorSet(pointer=ExplodingPointer(), keys=recording.RecordingKeySink(j))
    s.release_all()  # must not raise
    assert "keys.release_all" in j.methods()
