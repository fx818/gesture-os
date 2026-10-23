"""Jev point B — semantic tiling.

The premise of this point is that the same application in different ROLES belongs in different
places. Most of these tests exist to protect that premise, because it is easy to break in ways
that still look like they work.
"""

import pytest

from app.decision.backends.rules import RuleProvider
from app.decision.judgment_config import load as load_judgment
from app.decision.points import b_tile_role as B
from app.decision.questions import PointId
from app.intents import Zone
from app.types import AppClass, LayoutSnapshot, MonitorInfo, Rect, WindowInfo

PCFG = load_judgment().point(PointId.B_TILE_ROLE)


def _win(app="ptyxis", title="", wid="1", focused=False):
    return WindowInfo(wid, app, title, Rect(0, 0, 800, 600), 0, 0, focused)


def _judge(window, kind=AppClass.TERMINAL, layout=None):
    return B.interpret(
        RuleProvider().judge(B.build_request(window, kind, layout, PCFG)), PCFG
    )


def test_the_cache_key_includes_the_title():
    # THE REGRESSION. Keying on the application alone made `ptyxis: tail -f /var/log/syslog` and
    # `ptyxis: anurag@host: ~` share one cache entry, so the second inherited "background" from
    # the first — destroying the only distinction this point exists to make. Verified live before
    # the fix.
    logs = B.build_request(_win(title="tail -f /var/log/syslog"), AppClass.TERMINAL, None, PCFG)
    shell = B.build_request(_win(title="anurag@host: ~"), AppClass.TERMINAL, None, PCFG)
    assert logs.cache_key != shell.cache_key


def test_the_cache_key_is_stable_for_the_same_window():
    a = B.build_request(_win(title="anurag@host: ~"), AppClass.TERMINAL, None, PCFG)
    b = B.build_request(_win(title="anurag@host: ~"), AppClass.TERMINAL, None, PCFG)
    assert a.cache_key == b.cache_key


def test_the_cache_key_changes_with_rev():
    # Editing the prompt must invalidate its own cache, as everywhere else.
    import dataclasses

    other = dataclasses.replace(PCFG, rev=PCFG.rev + 1)
    assert (
        B.build_request(_win(), AppClass.TERMINAL, None, PCFG).cache_key
        != B.build_request(_win(), AppClass.TERMINAL, None, other).cache_key
    )


def test_the_same_application_lands_differently_by_role():
    # The whole premise. A terminal you type in is not a terminal showing logs.
    assert _judge(_win(title="tail -f /var/log/syslog")).zone is Zone.BACKGROUND
    assert _judge(_win(title="anurag@host: ~")).zone is Zone.MAIN


def test_reference_material_goes_to_the_side_panel():
    got = _judge(_win("Chrome", "MediaPipe Hands documentation"), AppClass.BROWSER)
    assert got.zone is Zone.SIDE_PANEL


def test_title_evidence_outranks_the_application_class():
    # The class says what a program IS; the title says what it is FOR, which is the question.
    got = _judge(_win("code", "build.log - VS Code"), AppClass.CODE_EDITOR)
    assert got.zone is Zone.BACKGROUND


def test_an_unknown_window_is_suggested_at_zero_confidence():
    got = _judge(_win("mystery", "mystery"), AppClass.UNKNOWN)
    assert got.confidence == 0.0
    assert got.provisional


def test_the_act_threshold_is_lower_here_than_for_app_context():
    # Deliberate: this answer is shown as a highlight the user can override with one flick, so a
    # medium-confidence suggestion is worth acting on. Point A drives a gesture MAP and is not.
    a = load_judgment().point(PointId.A_APP_CONTEXT)
    assert PCFG.act_threshold < a.act_threshold


def test_state_describes_the_layout_in_words_not_rectangles():
    # Jev cannot compare rectangles. The geometry is resolved in code and only the conclusion is
    # sent, exactly as with point F.
    layout = LayoutSnapshot(
        monitors=(MonitorInfo(0, Rect(0, 0, 1920, 1080), True),),
        windows=(_win("code", "main.py", wid="2", focused=True),),
        t_ms=0.0,
    )
    state = B.build_request(_win(wid="1"), AppClass.TERMINAL, layout, PCFG).state
    assert state["currently_in_main"] == "code"
    assert not any(isinstance(v, (int, float)) for v in state.values())


def test_a_value_outside_the_closed_set_degrades_to_main():
    from app.decision.provider import Judgment, Source

    got = B.interpret({"zone": Judgment("zone", "somewhere_else", 0.99, Source.JEV)}, PCFG)
    assert got.zone is Zone.MAIN


def test_every_declared_option_maps_to_a_real_zone():
    # A yaml option with no corresponding Zone would silently become MAIN at runtime.
    for option in PCFG.questions["zone"].options:
        assert option in B._ZONES
