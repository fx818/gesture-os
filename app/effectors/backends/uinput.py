"""Input injection via /dev/uinput.

Works below the display server, so it is unaffected by Wayland's restrictions on synthetic input —
unlike xdotool (X11 only) or AT-SPI injection (returns cleanly and is frequently a silent no-op,
see ADR-0003).

Requires a udev rule and `input` group membership; see README. `available()` reports honestly so
`doctor` and `wiring` can degrade instead of crashing at import time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from app.intents import Button
from app.types import Capability

UINPUT = Path("/dev/uinput")

_BUTTONS = {Button.LEFT: "BTN_LEFT", Button.RIGHT: "BTN_RIGHT", Button.MIDDLE: "BTN_MIDDLE"}

# Named so a user can find the device in `libinput list-devices` and target it with a quirk to
# disable pointer acceleration.
DEVICE_NAME = "gesture-os-virtual-input"

_KEY_ALIASES = {
    "super": "KEY_LEFTMETA",
    "meta": "KEY_LEFTMETA",
    "ctrl": "KEY_LEFTCTRL",
    "control": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT",
    "alt": "KEY_LEFTALT",
    "pageup": "KEY_PAGEUP",
    "pagedown": "KEY_PAGEDOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "tab": "KEY_TAB",
    "esc": "KEY_ESC",
}


def available() -> tuple[bool, str]:
    try:
        import evdev  # noqa: F401
    except ImportError:
        return False, "python3-evdev not installed (apt install python3-evdev)"
    if not UINPUT.exists():
        return False, "/dev/uinput missing — modprobe uinput"
    if not os.access(UINPUT, os.W_OK):
        return False, "/dev/uinput not writable — see the udev rule in README"
    return True, ""


def _keycode(name: str) -> int:
    from evdev import ecodes

    key = _KEY_ALIASES.get(name.lower(), f"KEY_{name.upper()}")
    code = getattr(ecodes, key, None)
    if code is None:
        raise KeyError(f"unknown key {name!r} (tried {key})")
    return int(code)


class UInputBackend:
    """Implements both PointerSink and KeySink — one virtual device is simpler to reason about
    and appears once in `libinput list-devices`."""

    def __init__(self) -> None:
        ok, reason = available()
        if not ok:
            raise RuntimeError(reason)
        from evdev import UInput, ecodes

        self._e = ecodes
        self._ui = UInput(
            {
                ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
                ecodes.EV_KEY: (
                    [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE]
                    + [c for c in range(ecodes.KEY_ESC, ecodes.KEY_MICMUTE)]
                ),
            },
            name=DEVICE_NAME,
            version=1,
        )
        # Sub-pixel deltas would otherwise vanish into int(), and slow precise motion — the entire
        # point of precision mode — would be silently dropped.
        self._rx = 0.0
        self._ry = 0.0
        self._down: set[int] = set()

    # -- Effector ------------------------------------------------------------------

    def capabilities(self) -> frozenset[Capability]:
        return frozenset(
            {Capability.POINTER_REL, Capability.SCROLL, Capability.KEY_SYNTH}
        )

    def close(self) -> None:
        try:
            self.release_all()
        finally:
            self._ui.close()

    # -- PointerSink ---------------------------------------------------------------

    def move_rel(self, dx: float, dy: float) -> None:
        self._rx += dx
        self._ry += dy
        ix, iy = int(self._rx), int(self._ry)
        self._rx -= ix
        self._ry -= iy
        if ix:
            self._ui.write(self._e.EV_REL, self._e.REL_X, ix)
        if iy:
            self._ui.write(self._e.EV_REL, self._e.REL_Y, iy)
        if ix or iy:
            self._ui.syn()

    def button(self, btn: Button, down: bool) -> None:
        code = int(getattr(self._e, _BUTTONS[btn]))
        self._ui.write(self._e.EV_KEY, code, 1 if down else 0)
        self._ui.syn()
        (self._down.add if down else self._down.discard)(code)

    def scroll(self, dx: float, dy: float) -> None:
        if dy:
            self._ui.write(self._e.EV_REL, self._e.REL_WHEEL, int(dy))
        if dx:
            self._ui.write(self._e.EV_REL, self._e.REL_HWHEEL, int(dx))
        if dx or dy:
            self._ui.syn()

    # -- KeySink -------------------------------------------------------------------

    def key(self, name: str, down: bool) -> None:
        code = _keycode(name)
        self._ui.write(self._e.EV_KEY, code, 1 if down else 0)
        self._ui.syn()
        (self._down.add if down else self._down.discard)(code)

    def chord(self, keys: Sequence[str]) -> None:
        codes = [_keycode(k) for k in keys]
        for code in codes:
            self._ui.write(self._e.EV_KEY, code, 1)
        self._ui.syn()
        for code in reversed(codes):
            self._ui.write(self._e.EV_KEY, code, 0)
        self._ui.syn()

    def release_all(self) -> None:
        """Panic path. Idempotent, non-blocking, and never raises — it runs from the watchdog
        while the engine may be wedged, and there is nothing above it to handle a failure."""
        for code in list(self._down):
            try:
                self._ui.write(self._e.EV_KEY, code, 0)
            except Exception:  # noqa: BLE001
                pass
        self._down.clear()
        try:
            self._ui.syn()
        except Exception:  # noqa: BLE001
            pass
        self._rx = self._ry = 0.0
