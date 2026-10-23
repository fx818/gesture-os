"""The context service — the wire between the Jev layer and the frame loop.

Every Jev point passed its own tests while the loop still ran on `DecisionContext.empty()`, so
`app_class` was permanently unknown and nothing Jev knew ever reached the engine. These tests exist
so that cannot silently happen again.
"""

import time

from app.actions import load as load_actions
from app.context.store import ContextService
from app.decision.backends.rules import RuleProvider
from app.decision.broker import JudgmentBroker
from app.decision.judgment_config import load as load_judgment
from app.types import AppClass, FocusInfo

JCFG = load_judgment()


class FakeFocus:
    """Stands in for AT-SPI so this runs with no desktop."""

    def __init__(self, initial=None):
        self.current_focus = initial
        self.callbacks = []

    def current(self):
        return self.current_focus

    def subscribe(self, cb):
        self.callbacks.append(cb)
        return self

    def unsubscribe(self):
        self.callbacks.clear()

    def emit(self, focus):
        self.current_focus = focus
        for cb in list(self.callbacks):
            cb(focus)


def _focus(app="ptyxis", title="anurag@host: ~"):
    return FocusInfo(app, title, "frame", None, 0.0)


def _service(initial=None):
    fake = FakeFocus(initial)
    svc = ContextService(
        JudgmentBroker(RuleProvider()), JCFG, focus_source=fake, catalogue=load_actions()
    )
    return svc, fake


def _settle(svc, expected=None, timeout=2.0):
    """Drain until the app class is known (or matches `expected`).

    Waiting for "any drained item" is not enough: the service also prefetches point C, so a drain
    can return items without point A's answer having arrived yet. Wait for the OUTCOME.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        svc.drain()
        got = svc.snapshot(0.0).app_class
        if got is not AppClass.UNKNOWN and (expected is None or got is expected):
            return True
        time.sleep(0.02)
    return False


def test_a_cold_service_reports_unknown_and_infinite_staleness():
    # A guard gating on app_class must be able to tell "nothing known yet" from "known, and old".
    svc, _ = _service()
    ctx = svc.snapshot(1000.0)
    assert ctx.app_class is AppClass.UNKNOWN
    assert ctx.app_class_age_ms == float("inf")


def test_focus_change_produces_an_app_class():
    svc, fake = _service()
    svc.start()
    try:
        fake.emit(_focus("ptyxis"))
        assert _settle(svc, AppClass.TERMINAL)
        assert svc.snapshot(0.0).app_class is AppClass.TERMINAL
    finally:
        svc.stop()


def test_switching_apps_resets_the_class_rather_than_keeping_the_old_one():
    # Carrying the previous app's class over would apply the wrong gesture map to the new window
    # for the whole duration of the round trip.
    svc, fake = _service()
    svc.start()
    try:
        fake.emit(_focus("ptyxis"))
        assert _settle(svc, AppClass.TERMINAL)
        fake.emit(_focus("firefox", "GitHub — Mozilla Firefox"))
        assert svc.snapshot(0.0).app_class is AppClass.UNKNOWN
        assert _settle(svc, AppClass.BROWSER)
    finally:
        svc.stop()


def test_snapshot_never_blocks():
    # It is called once per frame inside a budget measured in tens of milliseconds.
    svc, fake = _service(_focus())
    svc.start()
    try:
        t0 = time.monotonic()
        for _ in range(200):
            svc.snapshot(0.0)
        elapsed_ms = (time.monotonic() - t0) * 1000
    finally:
        svc.stop()
    assert elapsed_ms < 50, f"200 snapshots took {elapsed_ms:.0f}ms"


def test_staleness_is_reported_honestly():
    svc, fake = _service()
    svc.start()
    try:
        fake.emit(_focus())
        assert _settle(svc)
        early = svc.snapshot(0.0).app_class_age_ms
        later = svc.snapshot(5000.0).app_class_age_ms
        assert later > early
    finally:
        svc.stop()


def test_redundant_focus_events_are_suppressed():
    # AT-SPI emits window:activate more than once for the same window; each one would otherwise
    # reset the class to UNKNOWN and re-request.
    svc, fake = _service()
    svc.start()
    try:
        fake.emit(_focus("ptyxis"))
        assert _settle(svc, AppClass.TERMINAL)
        fake.emit(_focus("ptyxis"))  # same target
        assert svc.snapshot(0.0).app_class is AppClass.TERMINAL
    finally:
        svc.stop()


def test_recent_actions_reach_the_context():
    svc, _ = _service()
    svc.note_action("tile_left")
    svc.note_action("next_workspace")
    assert svc.snapshot(0.0).recent_actions[-1] == "next_workspace"


def test_wedges_are_available_without_a_cache():
    # No cache wired means no prefetched ranking; it must return something rather than raising,
    # because the radial menu is drawn from this on the dwell path.
    svc, _ = _service()
    assert svc.wedges() == ()


def test_the_service_runs_without_a_focus_source():
    # No AT-SPI (a bare TTY, a broken a11y stack) must degrade, not crash: the system still works,
    # it just never learns an app class.
    svc = ContextService(JudgmentBroker(RuleProvider()), JCFG, focus_source=None)
    svc.start()
    try:
        assert svc.snapshot(0.0).app_class is AppClass.UNKNOWN
        assert svc.drain() == 0
    finally:
        svc.stop()
