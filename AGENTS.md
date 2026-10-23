# AGENTS.md — gesture-os

Unified Gesture Desktop OS. One RGB webcam replaces the mouse, keyboard shortcuts and window
manager on GNOME/Wayland. A local, numeric arbitration engine classifies hand motion frame by frame
into one of four modes; TypeSafe's Jev (a text-only System One classifier) supplies the *semantic*
judgments off the realtime path.

## Stack

- **language:** Python 3.14 (venv created with `--system-site-packages`)
- **perception:** MediaPipe Hands + OpenCV
- **judgment:** TypeSafe `typesafe-sdk` / Jev — classification only, never generation
- **input injection:** `/dev/uinput` via python-evdev (apt, not PyPI)
- **desktop integration:** AT-SPI via `gi.repository.Atspi`; GNOME Shell extension (GJS) in P6
- **hud:** GTK4 + gtk4-layer-shell
- **target:** Ubuntu 26.04 / GNOME Shell 50 / Wayland

## Key Directories

- `app/types.py` — cross-layer vocabulary (Frame, FeatureFrame, FeatureWindow, FocusInfo). Imports nothing of ours.
- `app/arbitration` — **the core deliverable.** Pure state machine, `step()` has no I/O, no clock, no globals.
- `app/features` — landmarks → features. Pure. Every distance ÷ palm width so fixtures are camera-independent.
- `app/perception` — the only place `mediapipe` / `cv2` may be imported
- `app/decision` — Jev. The only place `typesafe_sdk` may be imported. One file per point A–G.
- `app/effectors` — the only place `evdev` / `gi` / `dbus` may be imported
- `app/routing` — turns Intents into effector calls; owns the undo journal
- `config/default.toml` — every numeric threshold in the system
- `config/judgment/points.yaml` — every Jev instruction and confidence threshold
- `fixtures/sessions` — recorded landmark streams (NDJSON, normalized coords, not video)
- `fixtures/golden` — expected intent streams; behavior regressions show up as diffs here
- `extension/` — GNOME Shell extension (GJS), P6 only

### Runtime Surfaces
- `main.py` — entrypoint; subcommands doctor / record / replay / golden / judge / bench / run

### Dependency contract (CI-enforced by `lint-imports`)
- `arbitration` may NOT import `decision`, `effectors`, `perception`, `routing`
- `features` may import only `types` and `config`
- third-party SDKs are each confined to exactly one module (see Key Directories)

## Non-obvious constraints

- **Clock is data.** `time.monotonic()` is banned in `features/` and `arbitration/`; time arrives as
  `frame.t_ms`. Replay must be bit-reproducible.
- **Jev is never called per-frame.** It is ~150ms, rate-limited to 1200/min, and the scope doc
  promises no frames leave the machine. Four independent barriers enforce this — see ADR-0001.
- **Jev cannot count, do arithmetic, or compare dates.** Never ask it to. Closed-set picks, rubric
  scores and single truth judgments only.
- **Window titles are attacker-controlled** (`document.title`). They are sanitized, delimited, and
  only ever feed closed-set questions.
- **X11 tools do not work.** No xdotool, no wmctrl, no `xprop` for focus. Wayland.
