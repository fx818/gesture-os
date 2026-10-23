"""Effector ports — the boundary between the pure core and the operating system.

Six narrow, capability-scoped protocols rather than one god interface, because the backends behind
them differ wildly in what they can do and how likely they are to be unavailable. A `ButtonPress`
must not be coupled to whether a GNOME Shell extension happens to be installed.

Every backend answers `capabilities()` honestly. The router checks an intent's `requires` against
the union of what's present and reports UNSUPPORTED — visibly, on the HUD — rather than raising.
That is what lets `ShortcutWindowManager` (GNOME's own keybindings) ship V2 while the GJS
extension is still unwritten: it declares WINDOW_MOVE but not WINDOW_TILE_ARBITRARY.

Only `effectors/backends/*` may import evdev, gi, or dbus.
"""

from __future__ import annotations

from typing import Callable, Protocol, Sequence, runtime_checkable

from app.intents import Button
from app.types import (
    Capability,
    FocusInfo,
    HudState,
    LayoutSnapshot,
    UiAction,
    Wedge,
    WindowInfo,
)


@runtime_checkable
class Effector(Protocol):
    def capabilities(self) -> frozenset[Capability]: ...
    def close(self) -> None: ...


class Subscription(Protocol):
    def unsubscribe(self) -> None: ...


@runtime_checkable
class PointerSink(Effector, Protocol):
    """Relative motion only. Absolute positioning would require EV_ABS/INPUT_PROP_DIRECT, at which
    point libinput treats the device as a touchscreen — tap-to-click, no persistent cursor.
    See ADR-0002."""

    def move_rel(self, dx: float, dy: float) -> None: ...
    def button(self, btn: Button, down: bool) -> None: ...
    def scroll(self, dx: float, dy: float) -> None: ...
    def release_all(self) -> None:
        """Panic path. MUST be idempotent and MUST NOT block — it runs from the watchdog thread
        while the engine may be wedged."""
        ...


@runtime_checkable
class KeySink(Effector, Protocol):
    def key(self, name: str, down: bool) -> None: ...
    def chord(self, keys: Sequence[str]) -> None: ...
    def release_all(self) -> None: ...


@runtime_checkable
class FocusSource(Effector, Protocol):
    """Reads which window has focus. On Wayland this is AT-SPI, not xprop.

    `subscribe` is the supported path. Never poll `current()` in a loop to detect changes:
    AT-SPI reports ACTIVE per-application-last-active, so several windows read ACTIVE at once.
    """

    def current(self) -> FocusInfo | None: ...
    def subscribe(self, cb: Callable[[FocusInfo], None]) -> Subscription: ...


@runtime_checkable
class WindowManager(Effector, Protocol):
    """Two very different backends implement this. `ShortcutWindowManager` drives GNOME's own
    keybindings through a KeySink and can only do coarse moves. `ShellExtWindowManager` talks
    D-Bus to the GJS extension and can place arbitrary rectangles. Callers distinguish them by
    `capabilities()`, never by type."""

    def list_windows(self) -> Sequence[WindowInfo]: ...
    def layout(self) -> LayoutSnapshot | None: ...
    def send_to_monitor(self, wid: str | None, direction: str) -> None: ...
    def send_to_workspace(self, wid: str | None, direction: str) -> None: ...
    def show_desktop(self) -> None: ...
    def move_to_rect(self, wid: str, x: int, y: int, w: int, h: int) -> None:
        """Requires WINDOW_TILE_ARBITRARY. The one thing only the extension provides."""
        ...


@runtime_checkable
class OverlaySink(Effector, Protocol):
    def show_hud(self, hud: HudState) -> None: ...
    def show_radial(self, wedges: Sequence[Wedge], selected: int | None) -> None: ...
    def hide(self, layer: str) -> None: ...


@runtime_checkable
class UiAutomationSource(Effector, Protocol):
    """Only Jev points D (teach-by-demonstration) and G (semantic text selection) need this."""

    def snapshot_focused_tree(self, max_nodes: int) -> tuple[UiAction, ...]: ...
    def record_actions(self) -> Sequence[UiAction]: ...
    def surrounding_text(self, max_chars: int) -> str | None: ...


@runtime_checkable
class PowerSink(Effector, Protocol):
    """Suspends the machine. Deliberately the narrowest port in the system: one verb, no arguments.

    There is no resume side — the process is frozen with everything else — so a PowerSink call is
    the only effector call that never returns normally in the way the others do.
    """

    def suspend(self) -> None: ...


class EffectorSet:
    """The bundle the router dispatches against. Built once in runtime/wiring.py; nothing else
    constructs backends."""

    __slots__ = ("pointer", "keys", "focus", "windows", "overlay", "ui", "power")

    def __init__(
        self,
        *,
        pointer: PointerSink,
        keys: KeySink,
        focus: FocusSource | None = None,
        windows: WindowManager | None = None,
        overlay: OverlaySink | None = None,
        ui: UiAutomationSource | None = None,
        power: PowerSink | None = None,
    ) -> None:
        self.pointer = pointer
        self.keys = keys
        self.focus = focus
        self.windows = windows
        self.overlay = overlay
        self.ui = ui
        self.power = power

    def capabilities(self) -> frozenset[Capability]:
        caps: set[Capability] = set()
        for e in (self.pointer, self.keys, self.focus, self.windows, self.overlay, self.ui, self.power):
            if e is not None:
                caps |= e.capabilities()
        return frozenset(caps)

    def all(self) -> tuple[Effector, ...]:
        return tuple(
            e
            for e in (self.pointer, self.keys, self.focus, self.windows, self.overlay, self.ui, self.power)
            if e is not None
        )

    def release_all(self) -> None:
        """Panic. Best-effort across every sink that has one; never raises, because the caller is
        the watchdog and there is nothing above it to handle an exception."""
        for sink in (self.pointer, self.keys):
            try:
                sink.release_all()
            except Exception:  # noqa: BLE001 — a failing sink must not block the others
                pass

    def close(self) -> None:
        for e in self.all():
            try:
                e.close()
            except Exception:  # noqa: BLE001
                pass
