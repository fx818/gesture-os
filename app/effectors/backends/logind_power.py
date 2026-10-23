"""Suspend via systemd-logind.

Chosen over synthesising a KEY_SLEEP keypress. A keycode only suspends if something in the desktop
happens to be listening for it, which cannot be verified without actually putting the machine to
sleep — and a sleep gesture that silently does nothing is worse than one that refuses to wire.
logind answers `CanSuspend` first, so availability is checked without triggering anything.

No root needed: polkit grants suspend to an active local session.
"""

from __future__ import annotations

from app.types import Capability

BUS_NAME = "org.freedesktop.login1"
OBJECT_PATH = "/org/freedesktop/login1"
INTERFACE = "org.freedesktop.login1.Manager"

_CAPS = frozenset({Capability.SYSTEM_SUSPEND})


def _proxy():
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    return Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SYSTEM,  # logind is on the SYSTEM bus, not the session bus
        Gio.DBusProxyFlags.DO_NOT_AUTO_START,
        None,
        BUS_NAME,
        OBJECT_PATH,
        INTERFACE,
        None,
    )


def available() -> tuple[bool, str]:
    """(usable, reason). Never raises — callers use this to decide whether to wire the backend.

    `CanSuspend` returns "yes" / "na" / "challenge" / "no". Only "yes" is wired: "challenge" means
    polkit would prompt for a password, and a gesture cannot answer a password prompt.
    """
    try:
        proxy = _proxy()
        if proxy.get_name_owner() is None:
            return False, "logind is not running"
        answer = proxy.call_sync("CanSuspend", None, 0, 2000, None).unpack()[0]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    if answer != "yes":
        return False, f"logind says CanSuspend={answer!r}"
    return True, ""


class LogindPowerSink:
    def __init__(self, proxy=None) -> None:
        self._proxy = proxy if proxy is not None else _proxy()

    def capabilities(self) -> frozenset[Capability]:
        return _CAPS

    def suspend(self) -> None:
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        # interactive=False: never raise a polkit password prompt. If policy would challenge, this
        # fails loudly here rather than leaving an invisible dialog behind the overview.
        self._proxy.call_sync("Suspend", GLib.Variant("(b)", (False,)), 0, 5000, None)

    def close(self) -> None:
        self._proxy = None
