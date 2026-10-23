"""Null effectors — accept everything, do nothing.

The DEFAULT in development and tests. `capabilities()` is constructor-injected so a test can
simulate a degraded machine (no Shell extension, no AT-SPI) and assert the router degrades rather
than raises.
"""

from __future__ import annotations

from typing import Callable, Sequence

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

POINTER_CAPS = frozenset({Capability.POINTER_REL, Capability.SCROLL})
KEY_CAPS = frozenset({Capability.KEY_SYNTH})
FOCUS_CAPS = frozenset({Capability.FOCUS_READ})
WINDOW_CAPS = frozenset({Capability.WINDOW_MOVE})
WINDOW_FULL_CAPS = WINDOW_CAPS | {Capability.WINDOW_TILE_ARBITRARY, Capability.WINDOW_LIST}
OVERLAY_CAPS = frozenset({Capability.OVERLAY})
UI_CAPS = frozenset({Capability.UI_TREE_READ, Capability.UI_ACTION_RECORD})


class _Null:
    def __init__(self, caps: frozenset[Capability]) -> None:
        self._caps = caps

    def capabilities(self) -> frozenset[Capability]:
        return self._caps

    def close(self) -> None:
        return None


class NullSubscription:
    def unsubscribe(self) -> None:
        return None


class NullPointerSink(_Null):
    def __init__(self, caps: frozenset[Capability] = POINTER_CAPS) -> None:
        super().__init__(caps)

    def move_rel(self, dx: float, dy: float) -> None: ...
    def button(self, btn: Button, down: bool) -> None: ...
    def scroll(self, dx: float, dy: float) -> None: ...
    def release_all(self) -> None: ...


class NullKeySink(_Null):
    def __init__(self, caps: frozenset[Capability] = KEY_CAPS) -> None:
        super().__init__(caps)

    def key(self, name: str, down: bool) -> None: ...
    def chord(self, keys: Sequence[str]) -> None: ...
    def release_all(self) -> None: ...


class NullFocusSource(_Null):
    def __init__(self, caps: frozenset[Capability] = FOCUS_CAPS) -> None:
        super().__init__(caps)

    def current(self) -> FocusInfo | None:
        return None

    def subscribe(self, cb: Callable[[FocusInfo], None]) -> NullSubscription:
        return NullSubscription()


class NullWindowManager(_Null):
    def __init__(self, caps: frozenset[Capability] = WINDOW_CAPS) -> None:
        super().__init__(caps)

    def list_windows(self) -> Sequence[WindowInfo]:
        return ()

    def layout(self) -> LayoutSnapshot | None:
        return None

    def send_to_monitor(self, wid: str | None, direction: str) -> None: ...
    def send_to_workspace(self, wid: str | None, direction: str) -> None: ...
    def show_desktop(self) -> None: ...
    def move_to_rect(self, wid: str, x: int, y: int, w: int, h: int) -> None: ...


class NullOverlaySink(_Null):
    def __init__(self, caps: frozenset[Capability] = OVERLAY_CAPS) -> None:
        super().__init__(caps)

    def show_hud(self, hud: HudState) -> None: ...
    def show_radial(self, wedges: Sequence[Wedge], selected: int | None) -> None: ...
    def hide(self, layer: str) -> None: ...


class NullUiAutomationSource(_Null):
    def __init__(self, caps: frozenset[Capability] = UI_CAPS) -> None:
        super().__init__(caps)

    def snapshot_focused_tree(self, max_nodes: int) -> tuple[UiAction, ...]:
        return ()

    def record_actions(self) -> Sequence[UiAction]:
        return ()

    def surrounding_text(self, max_chars: int) -> str | None:
        return None


POWER_CAPS = frozenset({Capability.SYSTEM_SUSPEND})


class NullPowerSink:
    """Declares SYSTEM_SUSPEND and does nothing. This is what every test runs against — a real
    suspend in CI would freeze the machine running it."""

    def __init__(self, caps: frozenset[Capability] = POWER_CAPS) -> None:
        self._caps = caps

    def capabilities(self) -> frozenset[Capability]:
        return self._caps

    def suspend(self) -> None:
        pass

    def close(self) -> None:
        pass
