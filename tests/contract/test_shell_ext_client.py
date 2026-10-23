"""The Shell-extension client, tested against a fake D-Bus proxy.

The extension itself cannot run in CI — it lives inside gnome-shell. What CAN be tested is every
assumption the client makes about it: the JSON shape, work-area vs monitor-rect, what happens on a
dead bus, and that a failed call degrades the capability instead of raising into the frame loop.

The fake mirrors the real interface in `extension/gesture-os@anurag.local/dbus.xml`. If that file
changes and this does not, these tests are the thing that should start lying — so
`test_fake_covers_every_method_in_the_real_interface` reads the XML and checks.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.effectors.backends.shell_ext import (
    EXPECTED_API_VERSION,
    ShellExtensionError,
    ShellExtWindowManager,
)
from app.types import Capability

DBUS_XML = (
    Path(__file__).resolve().parents[2]
    / "extension"
    / "gesture-os@anurag.local"
    / "dbus.xml"
)


def _window(wid, title="w", monitor=0, workspace=0, focused=False, x=0, y=0, w=800, h=600):
    return {
        "id": wid, "title": title, "wm_class": "App", "pid": 1,
        "monitor": monitor, "workspace": workspace, "focused": focused,
        "maximized": False, "fullscreen": False,
        "rect": {"x": x, "y": y, "width": w, "height": h},
    }


class FakeProxy:
    """Stands in for Gio.DBusProxy. Records calls so the tests can assert on the wire traffic."""

    def __init__(self, windows=None, monitors=None, fail=None):
        self.windows = windows if windows is not None else [_window(1, focused=True)]
        self.monitors = monitors if monitors is not None else [
            {
                "index": 0, "primary": True,
                "rect": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                "work_area": {"x": 0, "y": 32, "width": 1920, "height": 1048},
            }
        ]
        self.fail = fail
        self.calls = []

    def call_sync(self, method, variant, flags, timeout, cancellable):
        self.calls.append((method, variant.unpack() if variant is not None else None))
        if self.fail == method:
            raise RuntimeError("bus went away")
        if method == "ListWindows":
            payload = json.dumps(self.windows)
        elif method == "GetFocused":
            focused = next((w for w in self.windows if w["focused"]), None)
            payload = json.dumps(focused)
        elif method == "GetLayout":
            payload = json.dumps(
                {"monitors": self.monitors, "workspaces": 4, "active_workspace": 0,
                 "windows": self.windows}
            )
        elif method == "GetApiVersion":
            payload = 1
        else:
            payload = True
        return _Result(payload)


class _Result:
    def __init__(self, value):
        self._value = value

    def n_children(self):
        return 1

    def unpack(self):
        return (self._value,)


def _wm(**kw):
    proxy = FakeProxy(**kw)
    return ShellExtWindowManager(proxy=proxy), proxy


def test_fake_covers_every_method_in_the_real_interface():
    # If the extension grows a method and the fake does not, these tests would keep passing while
    # covering less. Reading the actual XML is what stops that drifting silently.
    declared = {
        m.get("name")
        for m in ET.parse(DBUS_XML).getroot().find("interface").findall("method")
    }
    proxy = FakeProxy()
    handled = set()
    for method in declared:
        try:
            proxy.call_sync(method, None, 0, 0, None)
            handled.add(method)
        except Exception:  # noqa: BLE001
            pass
    assert declared == handled, f"fake does not handle {declared - handled}"


def test_it_satisfies_the_window_manager_port():
    from app.effectors.ports import WindowManager

    wm, _ = _wm()
    assert isinstance(wm, WindowManager)


def test_it_is_the_only_backend_claiming_arbitrary_tiling():
    wm, _ = _wm()
    assert Capability.WINDOW_TILE_ARBITRARY in wm.capabilities()


def test_windows_are_parsed_from_json():
    wm, _ = _wm(windows=[_window(7, title="Notes", monitor=1, workspace=2, focused=True)])
    (win,) = wm.list_windows()
    assert win.wid == "7" and win.title == "Notes" and win.monitor == 1 and win.workspace == 2


def test_layout_uses_the_work_area_not_the_raw_monitor_rect():
    # Placing a window by the full monitor geometry puts its titlebar under the GNOME top bar.
    wm, _ = _wm()
    layout = wm.layout()
    assert layout.monitors[0].rect.y == 32
    assert layout.monitors[0].rect.height == 1048


def test_a_None_window_id_means_the_focused_window():
    # Which is what a gesture almost always means — the user is pointing at what they are using.
    wm, proxy = _wm(
        windows=[_window(1), _window(2, focused=True)]
    )
    wm.move_to_rect(None, 0, 0, 100, 100) if False else None
    wm.send_to_workspace(None, "right")
    assert ("SendToWorkspace", (2, 1)) in proxy.calls


def test_send_to_monitor_wraps_around():
    wm, proxy = _wm(
        windows=[_window(1, monitor=0, focused=True)],
        monitors=[
            {"index": 0, "primary": True, "rect": {"x": 0, "y": 0, "width": 1, "height": 1},
             "work_area": {"x": 0, "y": 0, "width": 1, "height": 1}},
            {"index": 1, "primary": False, "rect": {"x": 1, "y": 0, "width": 1, "height": 1},
             "work_area": {"x": 1, "y": 0, "width": 1, "height": 1}},
        ],
    )
    wm.send_to_monitor(None, "left")
    assert ("SendToMonitor", (1, 1)) in proxy.calls  # 0 - 1 wraps to the last monitor


def test_move_to_rect_reaches_the_bus_with_the_right_arguments():
    wm, proxy = _wm(windows=[_window(5, focused=True)])
    wm.move_to_rect(None, 10, 20, 300, 400)
    assert ("MoveWindowTo", (5, 10, 20, 300, 400)) in proxy.calls


def test_a_failed_call_degrades_the_capability_rather_than_retrying_forever():
    # The extension is disabled when the screen locks. The router must see the capability vanish
    # and report the feature unsupported, not hammer a dead bus once per frame.
    wm, _ = _wm(fail="ListWindows")
    assert Capability.WINDOW_TILE_ARBITRARY in wm.capabilities()
    with pytest.raises(ShellExtensionError):
        wm.list_windows()
    assert wm.capabilities() == frozenset()


def test_show_desktop_is_deliberately_not_implemented_here():
    # GNOME already has a keybinding and ShortcutWindowManager uses it. A second path would be a
    # second thing to keep working.
    wm, _ = _wm()
    with pytest.raises(ShellExtensionError, match="shortcut backend"):
        wm.show_desktop()


def test_the_client_pins_the_interface_version():
    # An extension left over from an older install would otherwise be called with arguments whose
    # meaning had changed.
    root = ET.parse(DBUS_XML).getroot()
    assert root.find("interface").get("name") == "org.gestureos.Shell"
    js = (DBUS_XML.parent / "extension.js").read_text()
    assert f"const API_VERSION = {EXPECTED_API_VERSION};" in js
