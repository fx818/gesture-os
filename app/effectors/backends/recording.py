"""Recording effectors — do nothing, but remember exactly what was asked.

This is how CI asserts behaviour with no hardware: run a fixture through the whole stack against a
RecordingPointerSink and compare the call list. It is also the fallback demo path if every real
input backend turns out to be blocked on this machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

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

from app.effectors.backends import null


@dataclass(frozen=True, slots=True)
class Call:
    method: str
    args: tuple[Any, ...]

    def __str__(self) -> str:
        return f"{self.method}{self.args}"


@dataclass
class Journal:
    """Shared call log. Passed into every recording backend so one EffectorSet produces a single
    ordered transcript across pointer, keys and windows."""

    calls: list[Call] = field(default_factory=list)

    def record(self, method: str, *args: Any) -> None:
        self.calls.append(Call(method, args))

    def methods(self) -> list[str]:
        return [c.method for c in self.calls]

    def clear(self) -> None:
        self.calls.clear()

    def __len__(self) -> int:
        return len(self.calls)


class _Recording:
    def __init__(self, journal: Journal, caps: frozenset[Capability]) -> None:
        self.journal = journal
        self._caps = caps

    def capabilities(self) -> frozenset[Capability]:
        return self._caps

    def close(self) -> None:
        self.journal.record("close")


class RecordingPointerSink(_Recording):
    def __init__(self, journal: Journal, caps: frozenset[Capability] = null.POINTER_CAPS) -> None:
        super().__init__(journal, caps)

    def move_rel(self, dx: float, dy: float) -> None:
        self.journal.record("move_rel", dx, dy)

    def button(self, btn: Button, down: bool) -> None:
        self.journal.record("button", btn, down)

    def scroll(self, dx: float, dy: float) -> None:
        self.journal.record("scroll", dx, dy)

    def release_all(self) -> None:
        self.journal.record("pointer.release_all")


class RecordingKeySink(_Recording):
    def __init__(self, journal: Journal, caps: frozenset[Capability] = null.KEY_CAPS) -> None:
        super().__init__(journal, caps)

    def key(self, name: str, down: bool) -> None:
        self.journal.record("key", name, down)

    def chord(self, keys: Sequence[str]) -> None:
        self.journal.record("chord", tuple(keys))

    def release_all(self) -> None:
        self.journal.record("keys.release_all")


class RecordingFocusSource(_Recording):
    def __init__(
        self,
        journal: Journal,
        focus: FocusInfo | None = None,
        caps: frozenset[Capability] = null.FOCUS_CAPS,
    ) -> None:
        super().__init__(journal, caps)
        self._focus = focus
        self._subscribers: list[Callable[[FocusInfo], None]] = []

    def current(self) -> FocusInfo | None:
        self.journal.record("focus.current")
        return self._focus

    def subscribe(self, cb: Callable[[FocusInfo], None]) -> null.NullSubscription:
        self._subscribers.append(cb)
        return null.NullSubscription()

    def emit(self, focus: FocusInfo) -> None:
        """Test hook: simulate a window:activate without AT-SPI."""
        self._focus = focus
        for cb in self._subscribers:
            cb(focus)


class RecordingWindowManager(_Recording):
    def __init__(
        self,
        journal: Journal,
        windows: Sequence[WindowInfo] = (),
        caps: frozenset[Capability] = null.WINDOW_CAPS,
    ) -> None:
        super().__init__(journal, caps)
        self._windows = tuple(windows)

    def list_windows(self) -> Sequence[WindowInfo]:
        self.journal.record("list_windows")
        return self._windows

    def layout(self) -> LayoutSnapshot | None:
        self.journal.record("layout")
        return None

    def send_to_monitor(self, wid: str | None, direction: str) -> None:
        self.journal.record("send_to_monitor", wid, direction)

    def send_to_workspace(self, wid: str | None, direction: str) -> None:
        self.journal.record("send_to_workspace", wid, direction)

    def show_desktop(self) -> None:
        self.journal.record("show_desktop")

    def move_to_rect(self, wid: str, x: int, y: int, w: int, h: int) -> None:
        self.journal.record("move_to_rect", wid, x, y, w, h)


class RecordingOverlaySink(_Recording):
    def __init__(self, journal: Journal, caps: frozenset[Capability] = null.OVERLAY_CAPS) -> None:
        super().__init__(journal, caps)

    def show_hud(self, hud: HudState) -> None:
        self.journal.record("show_hud", hud.mode, round(hud.mode_confidence, 3))

    def show_radial(self, wedges: Sequence[Wedge], selected: int | None) -> None:
        self.journal.record("show_radial", tuple(w.action_id for w in wedges), selected)

    def hide(self, layer: str) -> None:
        self.journal.record("hide", layer)


class RecordingUiAutomationSource(_Recording):
    def __init__(
        self,
        journal: Journal,
        actions: Sequence[UiAction] = (),
        text: str | None = None,
        caps: frozenset[Capability] = null.UI_CAPS,
    ) -> None:
        super().__init__(journal, caps)
        self._actions = tuple(actions)
        self._text = text

    def snapshot_focused_tree(self, max_nodes: int) -> tuple[UiAction, ...]:
        self.journal.record("snapshot_focused_tree", max_nodes)
        return self._actions[:max_nodes]

    def record_actions(self) -> Sequence[UiAction]:
        self.journal.record("record_actions")
        return self._actions

    def surrounding_text(self, max_chars: int) -> str | None:
        self.journal.record("surrounding_text", max_chars)
        return self._text


class RecordingPowerSink(_Recording):
    def __init__(self, journal: Journal, caps: frozenset[Capability] = null.POWER_CAPS) -> None:
        super().__init__(journal, caps)

    def suspend(self) -> None:
        self.journal.record("suspend")
