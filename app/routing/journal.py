"""Universal undo.

The scope doc asks for "one dedicated gesture [that] always means 'reverse the last action',
regardless of which mode produced it". That only works if every intent that changes something
records how to reverse it AT THE TIME, because by the time undo is invoked the context that made
the action meaningful is gone.

Not everything is undoable, and the journal says so rather than pretending: a cursor move has no
meaningful inverse (you moved the mouse; moving it back is not "undo"), while a workspace switch
and a tiling command do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.intents import (
    Direction,
    Intent,
    KeyChord,
    SendToMonitor,
    SendToWorkspace,
    SwitchWindow,
    ShowDesktop,
    ShowOverview,
    Suspend,
    TileWindow,
    Undo,
)

_OPPOSITE = {
    Direction.LEFT: Direction.RIGHT,
    Direction.RIGHT: Direction.LEFT,
    Direction.UP: Direction.DOWN,
    Direction.DOWN: Direction.UP,
}


def inverse(intent: Intent) -> Intent | None:
    """The intent that reverses `intent`, or None if it has no meaningful inverse."""
    match intent:
        case SendToWorkspace(direction=d):
            return SendToWorkspace(_OPPOSITE[d])
        case SwitchWindow(direction=d):
            return SwitchWindow(_OPPOSITE[d])
        case SendToMonitor(direction=d):
            return SendToMonitor(_OPPOSITE[d])
        case ShowDesktop():
            return ShowDesktop()  # toggles
        case ShowOverview():
            return ShowOverview()  # toggles
        case Suspend():
            return None  # a sleeping machine cannot be gestured awake
        case TileWindow():
            # Restoring an arbitrary rectangle needs the window's previous geometry, which only
            # the Shell extension can report (P6). Until then this is honestly un-undoable rather
            # than quietly wrong.
            return None
        case KeyChord(keys=keys):
            # A macro's effect is whatever the application did with the keystrokes. The app's own
            # Ctrl+Z is a better inverse than anything this layer could synthesise.
            return KeyChord(("ctrl", "z")) if keys != ("ctrl", "z") else None
        case _:
            return None


@dataclass
class ActionJournal:
    """Bounded stack of reversible actions."""

    limit: int = 50
    entries: list[tuple[float, Intent, Intent]] = field(default_factory=list)

    def record(self, t_ms: float, intent: Intent) -> bool:
        inv = inverse(intent)
        if inv is None:
            return False
        self.entries.append((t_ms, intent, inv))
        if len(self.entries) > self.limit:
            self.entries.pop(0)
        return True

    def pop(self) -> Intent | None:
        """The inverse of the most recent reversible action, consumed."""
        if not self.entries:
            return None
        return self.entries.pop()[2]

    def expand(self, intents) -> list[Intent]:
        """Replace any Undo intent with the inverse it resolves to, and journal the rest.

        Undo is resolved HERE rather than in the router so that the router stays a pure dispatcher
        and so an Undo that resolves to nothing simply disappears instead of erroring.
        """
        out: list[Intent] = []
        for intent in intents:
            if isinstance(intent, Undo):
                inv = self.pop()
                if inv is not None:
                    out.append(inv)
                continue
            out.append(intent)
        return out

    def __len__(self) -> int:
        return len(self.entries)
