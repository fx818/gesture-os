"""Intents — what the arbitration engine emits.

The engine never touches an effector. It emits these value objects and `routing/` turns them into
calls. That buys two things:

  * a second recordable seam. Landmarks in, intents out. Golden intent streams in
    `fixtures/golden/` mean a behavior change shows up as a reviewable diff instead of "it feels
    flickery now".
  * capability-gated degradation. Each intent declares what it needs; the router checks against
    the live backend set and reports UNSUPPORTED rather than raising, so a missing GNOME Shell
    extension disables one feature instead of crashing the loop.

Imports `types` only — intents sit below every impure layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.types import Capability


class Button(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class Direction(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


class Zone(StrEnum):
    """Snap targets. MAIN/SIDE/BACKGROUND are also Jev point B's closed answer set."""

    MAIN = "main"
    SIDE_PANEL = "side_panel"
    BACKGROUND = "background"
    LEFT_HALF = "left_half"
    RIGHT_HALF = "right_half"
    MAXIMIZE = "maximize"


@dataclass(frozen=True, slots=True)
class Intent:
    """Base. Subclasses declare `requires` as a class-level frozenset."""

    requires: frozenset[Capability] = field(default=frozenset(), init=False, repr=False)

    @property
    def kind(self) -> str:
        return type(self).__name__


# --- pointer ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MoveCursor(Intent):
    dx: float
    dy: float
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.POINTER_REL}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class ButtonPress(Intent):
    button: Button
    down: bool
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.POINTER_REL}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class Scroll(Intent):
    dx: float
    dy: float
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.SCROLL}), init=False, repr=False
    )


# --- keyboard / macros -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KeyChord(Intent):
    keys: tuple[str, ...]  # e.g. ("super", "left")
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.KEY_SYNTH}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class RunMacro(Intent):
    macro_id: str
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.KEY_SYNTH}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class SwitchWindow(Intent):
    """Move focus to the adjacent window — Chrome to the terminal, not tab to tab.

    Requires only KEY_SYNTH, not WINDOW_MOVE. This is GNOME's own `cycle-windows` keybinding, so
    the compositor owns the window order and we never have to model it. That keeps the binding
    working with no window manager wired, which matters because the Shell extension is an upgrade
    rather than a dependency.
    """

    direction: Direction
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.KEY_SYNTH}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class ShowOverview(Intent):
    """Open GNOME's Activities overview — every window on the workspace, side by side.

    Requires only KEY_SYNTH. `org.gnome.mutter overlay-key` is 'Super' on this machine, so tapping
    Super alone toggles the overview; `toggle-overview` is unbound (`@as []`), which is why this
    does NOT use Super+S. Nothing in the user's gsettings has to change for it to work.
    """

    requires: frozenset[Capability] = field(
        default=frozenset({Capability.KEY_SYNTH}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class Suspend(Intent):
    """Put the machine to sleep. The only intent in the system that ends the session.

    It has no inverse — you cannot gesture your way out of a suspended laptop — so `journal.inverse`
    returns None for it rather than pretending Undo covers it.
    """

    requires: frozenset[Capability] = field(
        default=frozenset({Capability.SYSTEM_SUSPEND}), init=False, repr=False
    )


# --- window management -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SendToWorkspace(Intent):
    direction: Direction
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.WINDOW_MOVE}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class SendToMonitor(Intent):
    direction: Direction
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.WINDOW_MOVE}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class ShowDesktop(Intent):
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.WINDOW_MOVE}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class TileWindow(Intent):
    """Arbitrary-rectangle placement. This is the ONE thing the GNOME Shell extension buys —
    everything else above degrades to GNOME's own keybindings."""

    zone: Zone
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.WINDOW_TILE_ARBITRARY}), init=False, repr=False
    )


# --- overlay / hud ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShowRadial(Intent):
    wedges: tuple[str, ...]
    selected: int | None
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.OVERLAY}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class HideOverlay(Intent):
    layer: str
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.OVERLAY}), init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class SetParameter(Intent):
    """A continuous value, not an event. Emitted every frame while a slider is held, so the
    receiver must treat it as a level rather than a delta."""

    name: str
    value: float
    requires: frozenset[Capability] = field(
        default=frozenset({Capability.KEY_SYNTH}), init=False, repr=False
    )


# --- safety ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseAll(Intent):
    """Panic. Requires NOTHING on purpose: it must dispatch to every backend present, even a
    degraded set, and must never be filtered out by a capability check."""


@dataclass(frozen=True, slots=True)
class Undo(Intent):
    """Reverse the last journalled action, whichever mode produced it."""
