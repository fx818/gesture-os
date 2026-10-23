"""FocusSource backed by AT-SPI. The only reliable way to read focus on GNOME Wayland.

`xprop`/`_NET_ACTIVE_WINDOW` do not exist here, and `org.gnome.Shell.Eval` has been disabled since
GNOME 41. AT-SPI works today on this machine with no installs — `gi.repository.Atspi` and
PyGObject are already present for Python 3.14.

Two hard-won details, both of which produce subtly wrong behaviour if ignored:

  * **Never poll for focus.** AT-SPI's ACTIVE state is per-application-last-active, not global, so
    several windows report ACTIVE simultaneously. `current()` exists as a cold-start fallback and
    says so; `subscribe()` is the supported path.
  * **`Atspi.event_main()` blocks its thread** and owns a GLib main loop. The HUD will want the
    same loop later, so the intended layout is: GLib on the main thread, perception on a worker
    named "perception".
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from app.types import Capability, FocusInfo

_CAPS = frozenset({Capability.FOCUS_READ})


class _Subscription:
    def __init__(self, unsub: Callable[[], None]) -> None:
        self._unsub = unsub

    def unsubscribe(self) -> None:
        self._unsub()


class AtspiFocusSource:
    def __init__(self) -> None:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        self._atspi = Atspi
        Atspi.init()
        self._callbacks: list[Callable[[FocusInfo], None]] = []
        self._listener = None
        self._thread: threading.Thread | None = None
        self._started = time.monotonic()
        self._last_key: tuple[str, str] | None = None

    # -- Effector ------------------------------------------------------------------

    def capabilities(self) -> frozenset[Capability]:
        return _CAPS

    def close(self) -> None:
        self.stop()

    # -- FocusSource ---------------------------------------------------------------

    def current(self) -> FocusInfo | None:
        """Cold-start fallback only.

        AT-SPI reports ACTIVE per application, so on a busy desktop several windows claim it and
        this can return the wrong one. Use it to seed state at startup, never to detect a change.
        """
        A = self._atspi
        try:
            desktop = A.get_desktop(0)
        except Exception:
            return None

        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                for j in range(app.get_child_count()):
                    win = app.get_child_at_index(j)
                    states = win.get_state_set()
                    if states.contains(A.StateType.ACTIVE):
                        return self._to_info(win, app)
            except Exception:
                continue
        return None

    def subscribe(self, cb: Callable[[FocusInfo], None]) -> _Subscription:
        self._callbacks.append(cb)
        if self._listener is None:
            self._listener = self._atspi.EventListener.new(self._on_event)
            self._listener.register("window:activate")
        return _Subscription(lambda: self._callbacks.remove(cb))

    # -- loop control --------------------------------------------------------------

    def run_forever(self) -> None:
        """Blocking. Owns this thread's GLib main loop."""
        self._atspi.event_main()

    def start(self) -> None:
        """Run the loop on a background thread, for callers that own the main thread."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._atspi.event_main, name="atspi", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        try:
            self._atspi.event_quit()
        except Exception:
            pass
        self._thread = None

    # -- internals -----------------------------------------------------------------

    def _to_info(self, win, app) -> FocusInfo:
        return FocusInfo(
            app_name=(app.get_name() or "?").strip(),
            window_title=(win.get_name() or "").strip(),
            role=win.get_role_name() or "",
            pid=self._safe_pid(app),
            t_ms=(time.monotonic() - self._started) * 1000.0,
        )

    @staticmethod
    def _safe_pid(app) -> int | None:
        try:
            return int(app.get_process_id())
        except Exception:
            return None

    def _on_event(self, event) -> None:
        # AT-SPI raises on races with windows that are closing. A focus watcher that dies when a
        # window disappears is worse than one that drops an event.
        try:
            win = event.source
            app = win.get_application()
            info = self._to_info(win, app)
        except Exception:
            return

        # window:activate fires redundantly; suppress repeats of the same target.
        key = (info.app_name, info.window_title)
        if key == self._last_key:
            return
        self._last_key = key

        for cb in tuple(self._callbacks):
            try:
                cb(info)
            except Exception:
                pass  # a bad subscriber must not kill the watcher
