"""WindowManager backed by the GNOME Shell extension over D-Bus.

This is the only backend that can place a window at an arbitrary rectangle, which is the one thing
the compositor will not let an ordinary process do on Wayland. Everything else gesture-os needs —
workspace switching, half-tiling, show-desktop — `ShortcutWindowManager` already does with plain
key injection, which is why the extension stayed off the critical path all the way through V2.

Failure is expected and handled rather than exceptional: the extension is disabled when the screen
locks, uninstalled on a GNOME upgrade, or simply not installed. `available()` reports honestly and
`capabilities()` shrinks accordingly, so the router degrades a feature instead of crashing a loop.
"""

from __future__ import annotations

import json
from typing import Sequence

from app.types import (
    Capability,
    LayoutSnapshot,
    MonitorInfo,
    Rect,
    WindowInfo,
)

BUS_NAME = "org.gestureos.Shell"
OBJECT_PATH = "/org/gestureos/Shell"
INTERFACE = "org.gestureos.Shell"

# Bumped together with API_VERSION in extension.js. A mismatch means the extension on disk is not
# the one this client was written against; refusing is better than calling a method whose
# arguments have quietly changed meaning.
EXPECTED_API_VERSION = 1

_FULL_CAPS = frozenset(
    {
        Capability.WINDOW_MOVE,
        Capability.WINDOW_LIST,
        Capability.WINDOW_TILE_ARBITRARY,
    }
)


class ShellExtensionError(RuntimeError):
    pass


def _proxy(timeout_ms: int = 500):
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    return Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION,
        Gio.DBusProxyFlags.DO_NOT_AUTO_START,
        None,
        BUS_NAME,
        OBJECT_PATH,
        INTERFACE,
        None,
    )


def available() -> tuple[bool, str]:
    """(usable, reason). Never raises — callers use this to decide whether to wire the backend."""
    try:
        proxy = _proxy()
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    if proxy.get_name_owner() is None:
        return False, (
            "extension not running — install extension/gesture-os@anurag.local and "
            "`gnome-extensions enable gesture-os@anurag.local`"
        )
    try:
        result = proxy.call_sync("GetApiVersion", None, 0, 500, None)
        version = int(result.unpack()[0])
    except Exception:  # noqa: BLE001
        version = 0
    if version != EXPECTED_API_VERSION:
        return False, f"API version mismatch: extension reports {version}, client expects {EXPECTED_API_VERSION}"
    return True, ""


def _rect(d: dict) -> Rect:
    return Rect(x=int(d["x"]), y=int(d["y"]), width=int(d["width"]), height=int(d["height"]))


def _window(d: dict) -> WindowInfo:
    return WindowInfo(
        wid=str(d["id"]),
        app_name=str(d.get("wm_class") or ""),
        title=str(d.get("title") or ""),
        rect=_rect(d["rect"]),
        monitor=int(d.get("monitor", 0)),
        workspace=int(d.get("workspace", 0)),
        focused=bool(d.get("focused", False)),
    )


class ShellExtWindowManager:
    """`proxy` is injectable so the contract tests can run against a fake with no GNOME present."""

    def __init__(self, proxy=None) -> None:
        self._proxy = proxy if proxy is not None else _proxy()
        self._degraded = False

    # -- Effector ------------------------------------------------------------------

    def capabilities(self) -> frozenset[Capability]:
        # Once a call has failed, stop claiming the capability. The router then reports the
        # feature as unsupported — visibly — instead of retrying a dead bus every frame.
        return frozenset() if self._degraded else _FULL_CAPS

    def close(self) -> None:
        self._proxy = None

    # -- internals -----------------------------------------------------------------

    def _call(self, method: str, *args):
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        try:
            variant = GLib.Variant(f"({''.join(_SIGNATURES[method])})", args) if args else None
            result = self._proxy.call_sync(
                method, variant, 0, 500, None  # noqa: FBT003
            )
            return result.unpack()[0] if result.n_children() else None
        except Exception as e:  # noqa: BLE001
            self._degraded = True
            raise ShellExtensionError(f"{method}: {type(e).__name__}: {e}") from e

    # -- WindowManager -------------------------------------------------------------

    def list_windows(self) -> Sequence[WindowInfo]:
        return tuple(_window(d) for d in json.loads(self._call("ListWindows") or "[]"))

    def layout(self) -> LayoutSnapshot | None:
        raw = json.loads(self._call("GetLayout") or "null")
        if not raw:
            return None
        return LayoutSnapshot(
            monitors=tuple(
                MonitorInfo(
                    index=int(m["index"]),
                    # The WORK AREA, not the full monitor rect: placing a window by the raw
                    # monitor geometry puts its titlebar under the top bar.
                    rect=_rect(m.get("work_area") or m["rect"]),
                    primary=bool(m.get("primary")),
                )
                for m in raw.get("monitors", [])
            ),
            windows=tuple(_window(d) for d in raw.get("windows", [])),
            t_ms=0.0,
        )

    def focused(self) -> WindowInfo | None:
        raw = json.loads(self._call("GetFocused") or "null")
        return _window(raw) if raw else None

    def send_to_monitor(self, wid: str | None, direction: str) -> None:
        target = self._resolve(wid)
        if target is None:
            return
        snapshot = self.layout()
        count = len(snapshot.monitors) if snapshot else 1
        delta = -1 if direction == "left" else 1
        self._call("SendToMonitor", int(target.wid), (target.monitor + delta) % max(1, count))

    def send_to_workspace(self, wid: str | None, direction: str) -> None:
        target = self._resolve(wid)
        if target is None:
            return
        delta = -1 if direction in ("left", "up") else 1
        self._call("SendToWorkspace", int(target.wid), max(0, target.workspace + delta))

    def show_desktop(self) -> None:
        # Not the extension's job: GNOME already has a keybinding for it, and `ShortcutWindowManager`
        # handles it. Adding a redundant path here would be a second thing to keep working.
        raise ShellExtensionError("show_desktop is handled by the shortcut backend")

    def move_to_rect(self, wid: str, x: int, y: int, w: int, h: int) -> None:
        target = self._resolve(wid)
        if target is not None:
            self._call("MoveWindowTo", int(target.wid), int(x), int(y), int(w), int(h))

    def _resolve(self, wid: str | None) -> WindowInfo | None:
        """`None` means 'the focused window', which is what a gesture almost always means."""
        if wid is None:
            return self.focused()
        for win in self.list_windows():
            if win.wid == wid:
                return win
        return None


_SIGNATURES = {
    "MoveWindowTo": "tiiii",
    "SendToMonitor": "ti",
    "SendToWorkspace": "ti",
}
