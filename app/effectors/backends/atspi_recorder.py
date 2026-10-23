"""Recording what a user does, through AT-SPI. The input side of Jev point D.

The scope doc's teach-by-demonstration: perform a workflow once, and bind it to a gesture. The
hard part is not capturing events — it is that raw capture is *noisy*. A real recording contains
the misclick you corrected, the Slack window that stole focus for two seconds, and the menu you
opened by accident and closed again. Replaying that verbatim reproduces your mistakes.

So the recorder is deliberately dumb and keeps everything; deciding what was incidental is Jev
point D's job, because "was that step part of what you meant?" is a judgment, not a rule.

Events are captured as TEXT — "clicked 'Export'", "focused window 'Figma'" — which is both what
replay needs and exactly the shape Jev can read.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Sequence

from app.types import Capability, UiAction

_CAPS = frozenset({Capability.UI_ACTION_RECORD, Capability.UI_TREE_READ})

# AT-SPI events worth recording. Keystrokes are deliberately NOT captured: a recorder that logs
# every key is a keylogger, and the workflows this is for are made of clicks and window changes.
_EVENTS = (
    "window:activate",
    "object:state-changed:focused",
    "object:selection-changed",
)

# Ignore events from our own HUD and from the shell itself — they are not part of any workflow.
_IGNORED_APPS = frozenset({"gnome-shell", "gesture-os"})


class AtspiRecorder:
    def __init__(self) -> None:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        self._atspi = Atspi
        Atspi.init()
        self._actions: list[UiAction] = []
        self._listeners: list = []
        self._lock = threading.Lock()
        self._started = 0.0
        self._thread: threading.Thread | None = None
        self._last: tuple[str, str, str] | None = None

    def capabilities(self) -> frozenset[Capability]:
        return _CAPS

    def close(self) -> None:
        self.stop()

    # -- recording -----------------------------------------------------------------

    def start(self) -> None:
        self._actions.clear()
        self._started = time.monotonic()
        self._last = None
        for name in _EVENTS:
            listener = self._atspi.EventListener.new(self._on_event)
            listener.register(name)
            self._listeners.append(listener)
        self._thread = threading.Thread(
            target=self._atspi.event_main, name="recorder", daemon=True
        )
        self._thread.start()

    def stop(self) -> Sequence[UiAction]:
        try:
            self._atspi.event_quit()
        except Exception:  # noqa: BLE001
            pass
        for listener in self._listeners:
            try:
                listener.deregister_all()
            except Exception:  # noqa: BLE001
                pass
        self._listeners.clear()
        self._thread = None
        with self._lock:
            return tuple(self._actions)

    def record_actions(self) -> Sequence[UiAction]:
        with self._lock:
            return tuple(self._actions)

    def snapshot_focused_tree(self, max_nodes: int) -> tuple[UiAction, ...]:
        return self.record_actions()[:max_nodes]

    def surrounding_text(self, max_chars: int) -> str | None:
        return None

    # -- internals -----------------------------------------------------------------

    def _on_event(self, event) -> None:
        # AT-SPI raises freely on races with dying widgets. A recorder that dies mid-workflow is
        # worse than one that drops an event.
        try:
            source = event.source
            app = source.get_application()
            app_name = (app.get_name() or "?").strip()
            if app_name in _IGNORED_APPS:
                return
            role = source.get_role_name() or ""
            name = (source.get_name() or "").strip()
            verb = "focus" if "focus" in event.type else (
                "activate" if "activate" in event.type else "select"
            )
        except Exception:
            return

        # Collapse repeats: AT-SPI emits the same focus event several times, and a workflow full
        # of duplicates is a workflow Jev has to read three times to understand once.
        key = (verb, role, name)
        if key == self._last:
            return
        self._last = key

        with self._lock:
            self._actions.append(
                UiAction(
                    t_ms=(time.monotonic() - self._started) * 1000.0,
                    verb=verb,
                    target_role=role,
                    target_name=name,
                    app_name=app_name,
                )
            )


# Re-exported for convenience; the implementations live below the effector layer so that
# `decision` can use them too (see app/ui_actions.py).
from app.ui_actions import describe, render  # noqa: E402,F401
