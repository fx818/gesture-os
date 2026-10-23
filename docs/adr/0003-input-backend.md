# ADR-0003 — Which backend injects input on GNOME 50 / Wayland

**Status:** open — P0.13 inconclusive, P0.14 blocked · 2026-09-18

## Context

X11 tools (xdotool, wmctrl) do not work in a Wayland session. Three candidate paths:

1. **AT-SPI** — `Atspi.generate_mouse_event` / `generate_keyboard_event`. No sudo, no udev, no
   group membership. This is the machinery Orca uses.
2. **`/dev/uinput` via python-evdev** — operates below the display server, so it works regardless
   of compositor. Needs a udev rule and `input` group membership.
3. **XDG RemoteDesktop portal / libei** — sanctioned, but adds a permission dialog and more moving
   parts.

## P0.13 — AT-SPI spike: INCONCLUSIVE

`Atspi.generate_mouse_event(x, y, "abs")` is present and **returns without raising**. That is not
evidence that the compositor honoured it: on Wayland, AT-SPI injection from a non-assistive client
is frequently a silent no-op, and the call has no return value to distinguish the two.

The pointer position could not be read back to confirm — `org.gnome.Shell.Eval` returns
`(false, '')`, which is expected and correct on GNOME 50 (it has been disabled outside unsafe mode
since GNOME 41), and Wayland gives ordinary clients no other way to query the global pointer.

**Open question, needs a human looking at the screen:** run
`python tools/spikes/p0_13_atspi_pointer.py` and watch whether the cursor jumps.

## P0.14 — uinput spike: BLOCKED

Requires two privileged one-time steps that have not been run:

```bash
sudo apt install -y python3-evdev
sudo tee /etc/udev/rules.d/60-gesture-os.rules <<'RULE'
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"
RULE
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG input "$USER"   # then log out and back in
```

## Consequence for now

Neither result blocks P1–P3. `PointerSink` and `KeySink` exist with null and recording backends,
and the whole engine is developed and tested against those. The decision is only needed at P4, and
the port means it is a one-flag change at wiring time when it is made.
