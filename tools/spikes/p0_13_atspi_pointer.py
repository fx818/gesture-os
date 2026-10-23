#!/usr/bin/env python3
"""P0.13 — can AT-SPI move the pointer on GNOME Wayland?

If yes, input injection needs no /dev/uinput, no udev rule, no `input` group and no sudo, and the
highest-risk item in the plan evaporates. Orca drives this same machinery, so it is not exotic.

Restores the original pointer position on the way out.
"""
import sys, time

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

Atspi.init()

have_mouse = hasattr(Atspi, "generate_mouse_event")
have_kbd = hasattr(Atspi, "generate_keyboard_event")
print(f"Atspi.generate_mouse_event    present: {have_mouse}")
print(f"Atspi.generate_keyboard_event present: {have_kbd}")
if not have_mouse:
    print("RESULT: unavailable — fall back to uinput (P0.14)")
    sys.exit(1)

try:
    from gi.repository import Gdk
    gi.require_version("Gdk", "4.0")
except Exception:
    Gdk = None

def where():
    """Best-effort pointer read. Wayland deliberately makes this hard for ordinary clients."""
    try:
        import subprocess
        out = subprocess.run(["gdbus", "call", "--session", "-d", "org.gnome.Shell",
                              "-o", "/org/gnome/Shell", "-m", "org.gnome.Shell.Eval",
                              "global.get_pointer()"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None

before = where()
print(f"pointer before: {before or '(unreadable — Shell.Eval is disabled, expected on GNOME 50)'}")

for target in ((200, 200), (600, 400)):
    try:
        Atspi.generate_mouse_event(target[0], target[1], "abs")
        print(f"  generate_mouse_event{target} -> returned without error")
    except Exception as e:
        print(f"  generate_mouse_event{target} -> {type(e).__name__}: {e}")
        print("RESULT: AT-SPI injection raised — fall back to uinput (P0.14)")
        sys.exit(1)
    time.sleep(0.4)

after = where()
print(f"pointer after:  {after or '(unreadable)'}")
print()
print("RESULT: calls succeeded. LOOK AT YOUR SCREEN — did the cursor actually jump?")
print("        AT-SPI returning cleanly does NOT prove the compositor honoured the event;")
print("        on Wayland it is frequently a silent no-op for non-a11y clients.")
