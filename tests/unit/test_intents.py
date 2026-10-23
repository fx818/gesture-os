"""Intents are the seam golden tests record, and the unit the router gates on capability.
These tests pin the two properties that seam depends on."""

import dataclasses

import pytest

from app.intents import (
    Button,
    ButtonPress,
    Direction,
    HideOverlay,
    Intent,
    KeyChord,
    MoveCursor,
    ReleaseAll,
    Scroll,
    SendToMonitor,
    ShowDesktop,
    ShowRadial,
    TileWindow,
    Undo,
    Zone,
)
from app.types import Capability

ALL_INTENTS = [
    MoveCursor(1.0, 2.0),
    ButtonPress(Button.LEFT, True),
    Scroll(0.0, 1.0),
    KeyChord(("super", "left")),
    SendToMonitor(Direction.LEFT),
    ShowDesktop(),
    TileWindow(Zone.MAIN),
    ShowRadial(("a", "b"), None),
    HideOverlay("radial"),
    ReleaseAll(),
    Undo(),
]


@pytest.mark.parametrize("intent", ALL_INTENTS, ids=lambda i: i.kind)
def test_every_intent_is_frozen(intent):
    # Golden intent streams and the undo journal both hold references to emitted intents. If one
    # were mutable, a later mutation would silently rewrite history.
    field_names = [f.name for f in dataclasses.fields(intent) if f.name != "requires"]
    if not field_names:
        pytest.skip("no mutable surface to test")
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(intent, field_names[0], object())


@pytest.mark.parametrize("intent", ALL_INTENTS, ids=lambda i: i.kind)
def test_every_intent_declares_capabilities_as_a_frozenset(intent):
    # The router does a subset check against the live backend set; a list or None here would
    # silently pass or explode at dispatch time instead of at construction.
    assert isinstance(intent.requires, frozenset)
    assert all(isinstance(c, Capability) for c in intent.requires)


def test_panic_requires_nothing():
    # ReleaseAll must survive a capability filter even when the effector set is degraded — a
    # panic that can be filtered out is not a kill switch.
    assert ReleaseAll().requires == frozenset()


def test_arbitrary_tiling_is_the_only_intent_gated_on_the_shell_extension():
    # This encodes the sequencing decision: V2 ships without the GJS extension because nothing
    # except arbitrary-rectangle placement needs WINDOW_TILE_ARBITRARY. If a new intent starts
    # requiring it, that decision needs revisiting — so this test should fail loudly.
    gated = {i.kind for i in ALL_INTENTS if Capability.WINDOW_TILE_ARBITRARY in i.requires}
    assert gated == {"TileWindow"}


def test_window_intents_used_by_v2_need_only_window_move():
    # These three are the gross gestures the scope doc actually names. They must be satisfiable
    # by ShortcutWindowManager (GNOME's own keybindings), not by the extension.
    for intent in (SendToMonitor(Direction.LEFT), ShowDesktop()):
        assert intent.requires == frozenset({Capability.WINDOW_MOVE})


def test_kind_is_the_class_name_for_golden_stream_stability():
    # Golden fixtures key on .kind; renaming a class is therefore a visible fixture diff.
    assert MoveCursor(0.0, 0.0).kind == "MoveCursor"
    assert isinstance(MoveCursor(0.0, 0.0), Intent)
