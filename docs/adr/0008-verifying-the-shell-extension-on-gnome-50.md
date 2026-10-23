# ADR-0008 — How to verify a Shell extension on GNOME 50 (and three ways I got it wrong)

**Status:** accepted · 2026-09-18 · verified end to end

## The working recipe

```bash
tools/verify_extension.sh          # wraps all of the below
```

which is, in full:

```bash
dbus-run-session -- bash -c '
  export WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/$(id -u)
  gnome-shell --devkit --virtual-monitor 1920x1080 &
  # wait for org.gnome.Shell on the session bus, then:
  gnome-extensions enable gesture-os@anurag.local
  # launch test apps against the NESTED display, not the host one:
  WAYLAND_DISPLAY=wayland-1 gnome-text-editor &
  gdbus call --session -d org.gestureos.Shell -o /org/gestureos/Shell \
    -m org.gestureos.Shell.MoveWindowTo <id> 120 140 640 480
'
```

Verified result: a real window moved from `(610,294) 700x520` to `(120,140) 640x480`.

## Three things that were wrong, and what each looked like

**1. `--nested` does not exist in GNOME Shell 50.** It is `--devkit`; nesting is now the default
and `--display-server` is the opt-out. The plan and TODO both told the user to run
`gnome-shell --nested`, which fails with `Unknown option --nested`.

The failure mode is the expensive part: the shell never starts, so every subsequent D-Bus call
returns `ServiceUnknown`, which is indistinguishable from an extension that failed to load. I
chased a phantom bug for several rounds. **Always check that the thing under test actually
started before believing anything about its behaviour.**

**2. Without `--virtual-monitor`, the devkit session has no monitors.** Windows land on
`monitor: -1`, and `move_resize_frame` returns success while changing nothing — the extension
reported `(true,)` and the geometry stayed put. Silent no-ops are the worst category of failure and
this one is environmental, not a code bug.

**3. Apps must be launched against the nested display.** The devkit shell creates its own Wayland
socket (`wayland-1`). An app launched with the host's `WAYLAND_DISPLAY` connects to the *host*
compositor and never appears in the session under test — which reads as "the extension cannot see
windows".

## A real bug this did find

`Meta.Window.get_maximized()` does not exist in Mutter 50. `MoveWindowTo` threw
`win.get_maximized is not a function` the moment any window existed. The current API, confirmed by
introspecting `Meta-18.typelib`:

- `win.is_maximized()` — boolean, replaces `get_maximized()`
- `win.unmaximize()` — **takes no arguments** now, not `MaximizeFlags`

Everything else the extension uses (`get_id`, `get_frame_rect`, `move_resize_frame`,
`move_to_monitor`, `change_workspace_by_index`, `get_window_type`) is unchanged.

## Two changes made on a misdiagnosis

Both were made while chasing the phantom, and both are being kept — but for honest reasons rather
than the ones I had at the time:

- **`ApiVersion` property → `GetApiVersion()` method.** I blamed a `_handlePropertyGet` error that
  turned out to come from GNOME's own `org.gnome.Shell.Extensions` GUI process, not from this
  extension. A method is still the better choice here (this interface is called from Python, never
  browsed), but the property was probably fine.
- **`version` → `version-name` in metadata.json.** Also not the cause. It is nonetheless correct
  for GNOME 45+, where the integer `version` is deprecated, and matches what shipped extensions do.
