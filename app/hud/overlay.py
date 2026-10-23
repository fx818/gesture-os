"""The confidence HUD.

The scope doc asks for "a small always-visible indicator [showing] the current mode and, during the
macro dwell window, a preview of which macro is about to fire, so the user can abort before it
executes". The abort window is the point: a macro dwell is 450ms, and a preview the user cannot see
is not a safety feature.

Two backends:

  * `LayerShellOverlay` — GTK4 + gtk4-layer-shell. The real one. On Wayland a layer-shell surface
    can float above everything WITHOUT taking focus, which matters enormously here: a HUD that
    stole focus would change which application the gesture system thinks you are in, and Jev point
    A's answer along with it. `gtk4-layer-shell` is not installed on this machine yet
    (`sudo apt install gir1.2-gtk4layershell-1.0`).
  * `TerminalOverlay` — a single rewritten line on stderr. No dependencies, works today, and is
    genuinely the better tool while developing because it interleaves with the logs.

Both implement `OverlaySink`, so `run --hud terminal` and `run --hud layer` differ by one flag.
"""

from __future__ import annotations

import shutil
import sys
from typing import Sequence

from app.types import Capability, HudState, Wedge

_BAR = "█"
_EMPTY = "·"


def _bar(value: float, width: int = 12) -> str:
    filled = max(0, min(width, round(value * width)))
    return _BAR * filled + _EMPTY * (width - filled)


class TerminalOverlay:
    """One line, rewritten in place on stderr so it does not interleave with stdout output."""

    def __init__(self, stream=None) -> None:
        self._out = stream or sys.stderr
        self._last = ""

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.OVERLAY})

    def close(self) -> None:
        self._write("")
        try:
            self._out.write("\n")
            self._out.flush()
        except Exception:  # noqa: BLE001
            pass

    def _write(self, text: str) -> None:
        width = shutil.get_terminal_size((100, 24)).columns
        line = text[: width - 1].ljust(len(self._last))
        try:
            self._out.write("\r" + line)
            self._out.flush()
        except Exception:  # noqa: BLE001 — a HUD must never take the loop down
            return
        self._last = line

    def show_hud(self, hud: HudState) -> None:
        tracked = "no hand" if hud.hands == 0 else f"{hud.hands} hand{'s' if hud.hands > 1 else ''}"
        parts = [
            f"[{hud.mode.value:<9}]",
            tracked,
            # Against gross.speed, so you can see whether a sweep is clearing the threshold.
            f"spd {hud.palm_speed:4.1f}",
            f"conf {_bar(hud.mode_confidence)} {hud.mode_confidence:.2f}",
            f"app {hud.app_class}",
        ]
        if hud.dwell_progress > 0.0:
            # The abort window. Showing WHAT is about to fire is the whole point — a countdown
            # with no name tells the user something is coming but not whether to stop it.
            preview = hud.dwell_preview or "?"
            parts.append(f"dwell {_bar(hud.dwell_progress, 8)} -> {preview} (open hands to abort)")
        if hud.degraded:
            parts.append(f"degraded: {','.join(hud.degraded)}")
        self._write("  ".join(parts))

    def show_radial(self, wedges: Sequence[Wedge], selected: int | None) -> None:
        names = [
            f"[{w.label}]" if i == selected else w.label for i, w in enumerate(wedges)
        ]
        self._write("radial: " + " ".join(names))

    def hide(self, layer: str) -> None:
        self._write("")


class LayerShellOverlay:
    """GTK4 layer-shell surface. Floats above everything without taking focus."""

    def __init__(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk, Gtk4LayerShell

        self._gtk = Gtk
        self._shell = Gtk4LayerShell
        self._window = Gtk.Window()
        Gtk4LayerShell.init_for_window(self._window)
        Gtk4LayerShell.set_layer(self._window, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_anchor(self._window, Gtk4LayerShell.Edge.BOTTOM, True)
        Gtk4LayerShell.set_margin(self._window, Gtk4LayerShell.Edge.BOTTOM, 24)
        # Critically: no keyboard interactivity. A HUD that took focus would change which
        # application has focus, and therefore what Jev point A reports, and therefore which
        # gesture map is active — the HUD would alter the behaviour it exists to display.
        Gtk4LayerShell.set_keyboard_mode(self._window, Gtk4LayerShell.KeyboardMode.NONE)
        self._label = Gtk.Label(label="")
        self._window.set_child(self._label)
        self._window.present()

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import gi

            gi.require_version("Gtk4LayerShell", "1.0")
            from gi.repository import Gtk4LayerShell  # noqa: F401
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: install gir1.2-gtk4layershell-1.0"
        return True, ""

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.OVERLAY})

    def close(self) -> None:
        try:
            self._window.close()
        except Exception:  # noqa: BLE001
            pass

    def show_hud(self, hud: HudState) -> None:
        text = f"{hud.mode.value}  {hud.hands}h  {hud.palm_speed:.1f}  {hud.mode_confidence:.2f}"
        if hud.dwell_progress > 0.0:
            text += f"   {hud.dwell_preview or '?'} in {1.0 - hud.dwell_progress:.0%}"
        self._label.set_text(text)

    def show_radial(self, wedges: Sequence[Wedge], selected: int | None) -> None:
        self._label.set_text(" · ".join(w.label for w in wedges))

    def hide(self, layer: str) -> None:
        self._label.set_text("")


def build(kind: str = "terminal"):
    """Pick an overlay, degrading to the terminal rather than failing to start."""
    if kind == "layer":
        ok, reason = LayerShellOverlay.available()
        if not ok:
            print(f"layer-shell overlay unavailable ({reason}) — using the terminal HUD",
                  file=sys.stderr)
            return TerminalOverlay()
        return LayerShellOverlay()
    if kind == "none":
        return None
    return TerminalOverlay()
