"""Intents -> effector calls, with capability-gated degradation.

An intent whose required capabilities are missing is reported as UNSUPPORTED and surfaced on the
HUD, never raised. A missing GNOME Shell extension must disable one feature, not crash the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.effectors.ports import EffectorSet
from app.intents import (
    ButtonPress,
    HideOverlay,
    Intent,
    KeyChord,
    MoveCursor,
    ReleaseAll,
    Scroll,
    SendToMonitor,
    SendToWorkspace,
    SwitchWindow,
    SetParameter,
    ShowDesktop,
    ShowOverview,
    Suspend,
    ShowRadial,
    TileWindow,
    Undo,
)

# GNOME's own keybindings cover every gross gesture the scope doc names, which is what keeps the
# Shell extension off the critical path — see the plan's "On the extension".
_WORKSPACE_KEYS = {"left": ("super", "pageup"), "right": ("super", "pagedown")}
# GNOME's `cycle-windows` (Alt+Escape), NOT `switch-windows` (Alt+Tab). Alt+Tab walks
# most-recently-used order and raises a popup switcher, so repeating it oscillates between the two
# newest windows instead of advancing — a sweep repeated three times would land back where it
# started. Alt+Escape cycles in stable order with no popup, which is what a repeated gesture needs.
_WINDOW_KEYS = {"left": ("shift", "alt", "esc"), "right": ("alt", "esc")}
_MONITOR_KEYS = {"left": ("super", "shift", "left"), "right": ("super", "shift", "right")}


@dataclass
class RouteReport:
    dispatched: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


class IntentRouter:
    def __init__(self, effectors: EffectorSet) -> None:
        self.fx = effectors
        self._caps = {c.value for c in effectors.capabilities()}

    def dispatch(self, intents, report: RouteReport | None = None) -> RouteReport:
        report = report or RouteReport()
        for intent in intents:
            missing = {c.value for c in intent.requires} - self._caps
            if missing:
                report.unsupported.append(f"{intent.kind} needs {sorted(missing)}")
                continue
            try:
                self._handle(intent)
                report.dispatched.append(intent.kind)
            except Exception as e:  # noqa: BLE001 — one bad effector must not stop the loop
                report.failed.append(f"{intent.kind}: {type(e).__name__}: {e}")
        return report

    def _handle(self, intent: Intent) -> None:
        fx = self.fx
        match intent:
            case MoveCursor(dx=dx, dy=dy):
                fx.pointer.move_rel(dx, dy)
            case ButtonPress(button=b, down=down):
                fx.pointer.button(b, down)
            case Scroll(dx=dx, dy=dy):
                fx.pointer.scroll(dx, dy)
            case KeyChord(keys=keys):
                fx.keys.chord(keys)
            case SendToWorkspace(direction=d):
                fx.keys.chord(_WORKSPACE_KEYS[d.value])
            case SwitchWindow(direction=d):
                fx.keys.chord(_WINDOW_KEYS[d.value])
            case SendToMonitor(direction=d):
                fx.keys.chord(_MONITOR_KEYS[d.value])
            case ShowDesktop():
                fx.keys.chord(("super", "d"))
            case Suspend():
                if fx.power is None:
                    raise NotImplementedError("no power sink wired")
                fx.power.suspend()
            case ShowOverview():
                # A bare Super TAP, which is what `overlay-key` listens for. Any other key pressed
                # between its press and release cancels the overview, so this must stay a chord of
                # one — adding a modifier here would silently turn it into a no-op.
                fx.keys.chord(("super",))
            case TileWindow(zone=zone):
                if fx.windows is None:
                    raise NotImplementedError("no window manager wired")
                # Geometry is resolved HERE, from the compositor's work area. Jev decided which
                # zone; turning that into pixels is arithmetic, which is code's job.
                from app.routing.zones import resolve

                rect = resolve(zone, fx.windows.layout())
                if rect is None:
                    raise NotImplementedError(f"cannot resolve {zone.value} without a layout")
                fx.windows.move_to_rect(None, rect.x, rect.y, rect.width, rect.height)
            case ShowRadial(wedges=wedges, selected=sel):
                if fx.overlay is not None:
                    from app.types import Wedge

                    fx.overlay.show_radial(
                        tuple(Wedge(w, w, 0.0) for w in wedges), sel
                    )
            case HideOverlay(layer=layer):
                if fx.overlay is not None:
                    fx.overlay.hide(layer)
            case SetParameter(name=name, value=value):
                # A level, not an event. GNOME exposes volume over its own keybindings, which is
                # coarse; a real implementation talks to PulseAudio. Emitting the step keys keeps
                # this honest about being a stub rather than silently doing nothing.
                fx.keys.chord(("volumeup",) if value > 0.5 else ("volumedown",))
            case ReleaseAll():
                fx.release_all()
            case Undo():
                fx.keys.chord(("ctrl", "z"))
            case _:
                raise NotImplementedError(f"no route for {intent.kind}")
