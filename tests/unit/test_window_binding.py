"""The gross sweep is bound to window switching. These tests pin the binding itself.

A test that only asserted "a SwitchWindow intent was produced" could not fail if the chord were
wrong, and the chord is the entire user-visible behaviour — a swipe that sends the wrong keys looks
identical in every log and does the wrong thing on screen.
"""

from app.effectors.backends import null, recording
from app.effectors.ports import EffectorSet
from app.intents import Direction, SwitchWindow
from app.routing.journal import inverse
from app.routing.router import IntentRouter
from app.types import Capability


def _chords(intent):
    j = recording.Journal()
    fx = EffectorSet(pointer=recording.RecordingPointerSink(j), keys=recording.RecordingKeySink(j))
    report = IntentRouter(fx).dispatch([intent])
    return [c.args[0] for c in j.calls if c.method == "chord"], report


def test_a_sweep_cycles_windows_rather_than_raising_the_alt_tab_switcher():
    # Alt+Escape (`cycle-windows`), NOT Alt+Tab (`switch-windows`). Alt+Tab walks most-recently-used
    # order, so repeating the sweep would bounce between the two newest windows instead of moving
    # through them — a gesture you can repeat is the whole point of binding it to a sweep.
    chords, _ = _chords(SwitchWindow(Direction.RIGHT))
    assert ("alt", "esc") in chords

    chords, _ = _chords(SwitchWindow(Direction.LEFT))
    assert ("shift", "alt", "esc") in chords


def test_window_switching_survives_a_machine_with_no_window_manager():
    # This is why SwitchWindow requires KEY_SYNTH rather than WINDOW_MOVE: GNOME owns the window
    # order via its own keybinding, so the gesture works with no WindowManager wired at all. The
    # Shell extension stays an upgrade rather than a dependency.
    assert SwitchWindow(Direction.LEFT).requires == frozenset({Capability.KEY_SYNTH})

    j = recording.Journal()
    keys_only = EffectorSet(
        pointer=recording.RecordingPointerSink(j),
        keys=recording.RecordingKeySink(j),
        windows=null.NullWindowManager(frozenset()),
    )
    report = IntentRouter(keys_only).dispatch([SwitchWindow(Direction.LEFT)])
    assert report.unsupported == []
    assert "SwitchWindow" in report.dispatched


def test_a_window_switch_is_undoable_in_the_opposite_direction():
    # Undo must cover every intent the system can emit; a sweep is the easiest gesture to fire by
    # accident, so the one bound to it losing its inverse would be the worst case.
    assert inverse(SwitchWindow(Direction.LEFT)) == SwitchWindow(Direction.RIGHT)
    assert inverse(SwitchWindow(Direction.RIGHT)) == SwitchWindow(Direction.LEFT)


def test_vertical_sweeps_are_bound_to_different_things_in_each_direction():
    # Up opens the overview, down suspends. Both directions are live, so the guard against a
    # mis-signed velocity is that they must never be confused: a swapped sign would suspend the
    # machine when the user asked to see their windows.
    from app.perception.backends.synthetic import GENERATORS
    from app.runtime.pipeline import run_pipeline

    def kinds(gen):
        j = recording.Journal()
        fx = EffectorSet(
            pointer=recording.RecordingPointerSink(j), keys=recording.RecordingKeySink(j)
        )
        r = run_pipeline(GENERATORS[gen](duration_s=0.8), fx)
        return {e.intent.kind for e in r.intents}

    # 0.8s, not the generator's 0.4s default: a sweep shorter than the 550ms window cannot satisfy
    # the enter guard at all, and horizontal sweeps fail the same way. That is the window, not the
    # binding — testing at 0.4s would assert the wrong thing and pass for the wrong reason.
    assert kinds("swipe_up") == {"ShowOverview"}
    assert kinds("swipe_down") == {"Suspend"}


def test_the_overview_is_a_bare_super_tap():
    # `org.gnome.mutter overlay-key` is 'Super', and `toggle-overview` is unbound on this machine.
    # Any second key pressed between Super's press and release CANCELS the overview, so adding a
    # modifier here would turn the gesture into a silent no-op that still looks dispatched.
    from app.intents import ShowOverview

    chords, report = _chords(ShowOverview())
    assert chords == [("super",)]
    assert "ShowOverview" in report.dispatched
    assert inverse(ShowOverview()) == ShowOverview()


def test_a_downward_sweep_suspends_and_is_explicitly_not_undoable():
    # Bound on request. This is the riskiest binding in the system — down is the direction hands
    # move involuntarily — so the test pins that it reaches a PowerSink and nothing else, and that
    # Undo does NOT claim to reverse it. A journal that offered an inverse here would be lying.
    from app.intents import Suspend
    from app.perception.backends.synthetic import GENERATORS
    from app.runtime.pipeline import run_pipeline

    j = recording.Journal()
    fx = EffectorSet(
        pointer=recording.RecordingPointerSink(j),
        keys=recording.RecordingKeySink(j),
        power=recording.RecordingPowerSink(j),
    )
    report = IntentRouter(fx).dispatch([Suspend()])
    assert report.dispatched == ["Suspend"]
    assert j.methods() == ["suspend"]
    assert inverse(Suspend()) is None

    def kinds(gen):
        jj = recording.Journal()
        f = EffectorSet(
            pointer=recording.RecordingPointerSink(jj),
            keys=recording.RecordingKeySink(jj),
            power=recording.RecordingPowerSink(jj),
        )
        r = run_pipeline(GENERATORS[gen](duration_s=0.8), f)
        return {e.intent.kind for e in r.intents}

    assert kinds("swipe_down") == {"Suspend"}
    assert kinds("swipe_up") == {"ShowOverview"}


def test_suspend_degrades_visibly_when_no_power_sink_is_wired():
    # A gesture that silently does nothing is the failure mode this project keeps hitting. Without
    # a PowerSink the router must SAY the capability is missing, not swallow the intent.
    from app.intents import Suspend

    j = recording.Journal()
    no_power = EffectorSet(
        pointer=recording.RecordingPointerSink(j), keys=recording.RecordingKeySink(j)
    )
    report = IntentRouter(no_power).dispatch([Suspend()])
    assert report.dispatched == []
    assert any("system.suspend" in u for u in report.unsupported)
