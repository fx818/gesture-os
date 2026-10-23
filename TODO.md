# TODO — Unified Gesture Desktop OS

**Updated:** 2026-09-18 · **Phase:** V2 gate · **Milestone:** MVP
**Last done:** P7g (downward sweep suspends) · **Next:** the logout
**Location:** `~/Desktop/gesture-os` (moved from `~/Documents` 2026-09-18 — the venv was
rebuilt, since its scripts carry absolute paths)
**Plan:** `~/.claude/plans/first-of-all-make-cosmic-plum.md` · **Scope:** `docs/scope.md`

## Rules

- Update this file after EVERY completed task, in the same commit as the code.
- One task = one checkbox + one `verify:` line. **No task without a verification command.**
- Status: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked · `[-]` dropped
- Ids `P<phase>.<n>`, never reused, never renumbered.
- Never delete completed items; `## Done` is the project changelog.
- Nothing leaves `## Gated` until its gate line is satisfied.
- A phase expands into numbered tasks when that phase *starts*, not before.

---

## Done — P0: skeleton and contracts

No camera, no Jev, no mediapipe. Exit when `make ci` is green with zero product code.

- [x] P0.1 Repo tree, package `__init__.py` files, git init
      verify: `find app -name __init__.py | wc -l` is 16
- [x] P0.2 Doc trio (CLAUDE.md, AGENTS.md, README.md) + scope doc copied to `docs/scope.md`
      verify: `ls CLAUDE.md AGENTS.md README.md docs/scope.md`
- [x] P0.3 `requirements.txt`, `.gitignore`, `.env.example`, `Makefile`
      verify: `make help` lists ci / ci-live / doctor / golden
- [x] P0.4 `app/types.py` — Frame, Hand, FeatureFrame, FeatureWindow, FocusInfo. Imports nothing of ours.
      verify: `pytest tests/unit/test_types.py`
- [x] P0.5 `app/intents.py` — Intent value objects
      verify: `pytest tests/unit/test_intents.py`
- [x] P0.6 `app/config.py` loader — frozen dataclass tree, asserts `sustain[m] < enter[m]` at load
      verify: `pytest tests/unit/test_config.py`
- [x] P0.7 `app/effectors/ports.py` — six capability-scoped ports + Capability enum
      verify: `pytest tests/contract/test_ports.py`
- [x] P0.8 Null + Recording effector backends (every port needs both)
      verify: `pytest tests/contract/test_pointer_sink_contract.py`
- [x] P0.9 `app/perception/source.py` protocol + NDJSON reader/writer + SyntheticLandmarkSource
      verify: `pytest tests/unit/test_ndjson_roundtrip.py`
- [x] P0.10 `app/cli.py` skeleton: doctor | replay | record | golden | judge | bench | run
      verify: `python main.py --help`
- [x] P0.11 import-linter contracts in `.importlinter` (your convention is no pyproject.toml)
      verify: `lint-imports`
- [x] P0.12 `tools/check_no_magic_numbers.py` — AST lint, no literals but 0/1/-1 in arbitration/ and decision/points/
      verify: `python tools/check_no_magic_numbers.py`
- [!] P0.13 SPIKE: `Atspi.generate_mouse_event(200,200,"abs")` — does the pointer move?
      verify: pointer visibly moves, or documented failure in `docs/adr/0003-input-backend.md`
- [!] P0.14 SPIKE: inject `Super+Left` via uinput — does a window tile?
      verify: window tiles, or documented failure in same ADR
- [x] P0.15 P0 EXIT: `python main.py replay --synthetic swipe_left --effector recording` runs end to end
      verify: `make ci` green

## Done — P1: Jev point A, no camera

Live and calibrated. `judge app-context` returns source=jev, then source=cache, and source=rules
under `--offline --no-cache`. Calibration: docs/verification/p1-calibration.md.

- [x] P1.1 SPIKE (15 min, before any code): 12 hardcoded (app, title) pairs from a live AT-SPI
      dump -> ONE system_one call. Eyeball categories and confidences, measure RTT.
      If the categories are wrong here, the question wording is wrong — fix it before building.
      verify: prints a category + confidence per pair, and a measured RTT
- [x] P1.2 `app/context/focus.py` — FocusInfo + normalize_title(); cache key (app, title, rev)
      verify: `pytest tests/unit/test_focus.py`
- [x] P1.3 `app/effectors/backends/atspi_focus.py` — subscribe to window:activate (never poll ACTIVE)
      verify: `python main.py watch-focus` prints app+title as you alt-tab
- [x] P1.4 `app/decision/questions.py` + `provider.py` — the vocabulary and the protocol
      verify: `pytest tests/contract/test_judgment_provider_contract.py`
- [x] P1.5 `app/decision/backends/rules.py` — offline fallback, honest confidences
      verify: contract suite passes against RuleProvider with no network
- [x] P1.6 `app/decision/backends/typesafe.py` — TypeSafeProvider (probe() already exists)
      verify: `pytest tests/live -m live`
- [x] P1.7 `app/decision/composite.py` — Caching / Budgeted / Fallback decorators
      verify: `pytest tests/unit/test_composite.py` incl. cache-key includes `rev`
- [x] P1.8 `app/decision/sanitize.py` — truncate, strip control chars, delimit untrusted fields
      verify: `pytest tests/unit/test_sanitize.py` incl. an injection attempt in a window title
- [x] P1.9 `app/decision/broker.py` — owns the only provider-calling thread
      verify: `pytest tests/perf/test_jev_firewall.py` asserts calls_from_loop_thread == 0
- [x] P1.10 `app/decision/points/a_app_context.py` + `config/judgment/points.yaml`
      verify: `python main.py judge app-context --app code --title "engine.py — VS Code"`
- [x] P1.11 Calibration harness: >=100 real window titles, accuracy per confidence bucket
      verify: prints the bucket table; thresholds in points.yaml set FROM it
- [x] P1.12 P1 EXIT: same query returns source=jev, then source=cache, and source=rules with --offline
      verify: all three, contract-tested

## Done — P2: perception + fixture corpus

- [x] P2.1 `mediapipe_camera.py` — threaded capture, per-stage timings, MJPG 640x480
      verify: `python main.py bench` prints the stage ladder
- [x] P2.2 `make model` fetches hand_landmarker.task (gitignored, 7.5MB)
- [x] P2.3 `record` / `record --synthetic` / `replay`
      verify: `python main.py record live-desk-6s --seconds 6` then replay it
- [x] P2.4 `bench` with warm-up excluded and reported separately
- [x] P2.5 11-fixture corpus, 4 of them negatives
      verify: `ls fixtures/sessions/`
- [!] P2.6 Record REAL gesture fixtures — see Blocked

## Done — P3: features + arbitration core

- [x] P3.1 `features/filters.py` One Euro as a pure fold
- [x] P3.2 `features/extract.py` — scale/translation invariant, velocity from raw position
- [x] P3.3 `features/window.py` — trimmed by time, not frame count
- [x] P3.4 `arbitration/guards.py` — composable combinators, confidence not bool
- [x] P3.5 `arbitration/engine.py` — pure `step()`, four hysteresis layers
- [x] P3.6 modes: idle / precision / macro / gross / panic
- [x] P3.7 `runtime/golden.py` + `golden --update|--check`
      verify: `python main.py golden` — 11/11 match
- [x] P3.8 tests: arbitration, features, hysteresis properties, pure-core perf budget
      verify: `make ci` — 206 passed

## Done — P4: execution

- [x] P4.1 `routing/router.py` — capability-gated dispatch, degrades never raises
- [x] P4.2 `effectors/backends/uinput.py` — relative deltas, fractional remainder, release_all
- [x] P4.3 `run` wired end to end
      verify: `python main.py run --seconds 10` on the real camera
- [!] P4.4 Verify uinput moves a real cursor — see Blocked

## Done — P5: V2 + Jev point F

- [x] P5.1 `app/poses.py` template library + `record-pose`; macro guard uses it
      verify: `pytest tests/unit/test_poses.py` — library ships EMPTY by design
- [x] P5.2 gross gestures -> key chords via `routing/router.py` (no Shell extension needed)
- [x] P5.3 `runtime/watchdog.py` — panic detector that never touches `step()`
      verify: `pytest tests/unit/test_watchdog.py` — 7 tests, incl. a failing effector
- [x] P5.4 `hud/overlay.py` — terminal HUD working; layer-shell degrades to it
      verify: dwell bar fills over 450ms with an abort prompt
- [x] P5.5 **Jev point F** — EventRing -> plain-language render -> `postmortem`
      verify: `python main.py postmortem` — live Jev, correctly returned unintended=false
- [x] P5.6 `tools/calibrate_thresholds.py` — per-mode threshold recommender
      verify: corrected gross.coherence 0.85 -> 0.70 from the real fixture
- [x] P5.7 `routing/journal.py` — universal undo with honest "not undoable" cases
      verify: `pytest tests/unit/test_journal.py`

## Done — P6: GNOME Shell extension + Jev point B

- [x] P6.1 `extension/gesture-os@anurag.local/` — GNOME 45+ ESM extension, versioned D-Bus iface
- [x] P6.2 ListWindows / GetLayout / GetFocused / MoveWindowTo / SendToMonitor / SendToWorkspace
- [x] P6.3 `effectors/backends/shell_ext.py` + 11 fake-D-Bus contract tests
      verify: `pytest tests/contract/test_shell_ext_client.py` — no GNOME needed
- [x] P6.4 **Jev point B** live — semantic tiling
      verify: `judge tile-role` distinguishes `tail -f` (background) from a shell (main)
- [x] P6.5 `routing/zones.py` — zone -> rectangle over the work area
- [!] P6.6 Load the extension in a real session — see Blocked

## Done — P7a: Jev points C and E

- [x] P7.0 `config/actions.yaml` + `app/actions.py` — the closed action catalogue both points need
      verify: `pytest tests/unit/test_actions.py`
- [x] P7.2 **Jev point E** live — natural-language binding, closed-set Choice per argument
      verify: "make a fist to save the file" -> pose:fist -> Save (0.97)
- [x] P7.1 **Jev point C** live — adaptive radial menu, PREFETCHED on context change
      verify: cache-warm dwell read in 0.3ms with Jev's ranking (ADR-0004 refinement)

## Done — P7.6: the Jev layer is actually wired in

Every point passed its own tests while `run` still used `DecisionContext.empty()` — app_class was
permanently unknown and nothing Jev knew reached the engine.

- [x] `app/context/store.py` — focus watcher + broker + prefetch -> DecisionContext
      verify: `pytest tests/unit/test_context_store.py`; live `run` shows `app unknown -> browser`
- [x] loop drains judgments per frame, never blocks (`snapshot()` is a read)
- [x] radial wedges shown during the macro dwell, from point C's prefetched cache
- [x] dispatched intents feed `note_action`, which re-prefetches point C
- [x] `run --no-context` / `--offline` still work with the whole layer disabled
- [x] README documents the usage constraints that were found the hard way

## Done — P7b: ALL SEVEN JEV POINTS LIVE

- [x] P7.3 **Jev point G** — semantic text selection
      `app/text_spans.py` (pure span arithmetic) + `effectors/backends/atspi_text.py`
      verify: url 0.97, quoted_string 0.92, line-in-code 0.62 against live Jev
- [x] P7.4 **Jev point D** — teach-by-demonstration cleanup
      `effectors/backends/atspi_recorder.py` + `app/ui_actions.py`
      verify: on a messy 8-step recording it dropped exactly the wrong menu and the Slack
      interruption, keeping the final button click

## Done — P7c: the local features

- [x] P7.5 `arbitration/chording.py` + `in_chord`/`no_chord` guards; chord reaches DecisionContext
      verify: `pytest tests/unit/test_chording.py` — modifier is the NON-ACTING hand, not "left"
- [x] P7.6 `arbitration/modes/slider.py` + `SetParameter` intent; armed only under a chord
      verify: config loader refused the mode until every threshold table listed it
- [x] P7.7 `arbitration/grammar.py` + `config/grammar.yaml` — compound phrases, time-windowed
      verify: `pytest tests/unit/test_grammar.py`
- [x] P7.8 `main.py teach <name>` — record -> point D -> macro bound to a pose

## Done — P7d: making real swipes actually fire

- [x] P7d.1 `_LatestFrameGrabber.latest()` returns a COPY under the lock — it handed out OpenCV's
      reusable capture buffer by reference, so the capture thread overwrote the array inference was
      still reading. Detection was HALVED (17/56 through the grabber vs 27/40 direct) and it looked
      like a lighting problem for days.
      verify: controlled re-test went 117/117 detected
- [x] P7d.2 GROSS enter guard `for_all_frames` -> `for_enter_fraction` (+ `arbitration.enter_fraction`)
      `for_all_frames` takes the MINIMUM across the window, so one dropped tracking frame scores 0.
      On a real swipe with 93% tracking, speed peaking 10.3 against a 1.8 threshold and sustained
      676ms against a 550ms window, the GROSS enter score was exactly 0.00 for the whole recording.
      verify: `pytest tests/unit/test_guards.py`; `live-swipe-check` now emits SendToWorkspace
- [x] P7d.3 `neg-idle-motion` unlabelled for `gross` — the fixture contains swipes, not idle motion
      (palm sweeps 0.562 of frame width twice; outscores the deliberate swipe on every gross
      feature). Three "clean" threshold sweeps were fitting to a bad label and each one cost the
      only real-hand positive. Thresholds stay 1.8/0.70; the calibrator independently agrees (1.81/0.71).
      verify: `python tools/calibrate_thresholds.py`; ADR-0011

## Done — P7e: the horizontal sweep switches WINDOWS

- [x] P7e.1 `SwitchWindow` intent + router binding to Alt+Escape / Shift+Alt+Escape
      Briefly bound to tab switching (Ctrl+PageUp/Down) on my misreading of "switch" — corrected:
      the point of a cross-app gesture is leaving the app you are in, not moving inside it.
      Requires KEY_SYNTH, NOT WINDOW_MOVE — this is GNOME's own `cycle-windows`, so the compositor
      owns the window order and the binding works with no WindowManager wired. `switch-windows`
      (Alt+Tab) was rejected for the same reason Ctrl+Tab was: it walks most-recently-used order
      and raises a popup, so a repeated sweep oscillates between two windows instead of advancing.
      verify: `pytest tests/unit/test_window_binding.py`; right -> alt+esc, left -> shift+alt+esc
- [x] P7e.2 downstream touchpoints updated together — `f_misfire` _ACTED regex, `sweep_thresholds`
      counter, `test_arbitration`, `test_grammar`, golden streams. `grammar.load()` does NOT
      validate sequence names against real intent kinds, so a stale name is a silent no-match;
      `send-left-and-pin` is now marked DORMANT in grammar.yaml rather than left looking live.
      verify: `make ci` — 372 passed

- [x] P7e.3 GNOME Shell extension WIRED — `cli.py _build_effectors("uinput")` now attaches
      `ShellExtWindowManager` when `shell_ext.available()` says so, and prints why when it does
      not. P6 built the extension, the client and the contract test but never constructed the
      backend in the product: it appeared only in a docstring, so the live system declared
      `['key.synth','pointer.rel','scroll']` and `fx.windows` was None. Now declares
      `window.list | window.move | window.tile.arbitrary`; `TileWindow` dispatches against a real
      window. Unblocks Jev point B.
      verify: `_build_effectors("uinput")` -> ShellExtWindowManager; TileWindow(LEFT_HALF) dispatched
- [x] P7e.4 "silent drop" investigated and REJECTED — there was no bug. `dispatch()` reports
      `unsupported` on a capability miss and `_handle` ends in `case _: raise NotImplementedError`,
      so an unroutable intent lands in `failed`. The empty RouteReport I reported came from my own
      probe: it used `Zone.LEFT`, which does not exist (members are MAIN, SIDE_PANEL, BACKGROUND,
      LEFT_HALF, RIGHT_HALF, MAXIMIZE), behind a `hasattr` guard that dispatched an empty list.
      verify: TileWindow(MAIN) with no windows port -> unsupported ["TileWindow needs [...]"]

## Done — P7f: the upward sweep opens the overview

- [x] P7f.1 `ShowOverview` intent -> a BARE Super tap (`overlay-key` is 'Super'; `toggle-overview`
      is unbound `@as []` here, so Super+S would be a no-op). Any second key between Super's press
      and release cancels the overview, so the chord must stay length 1.
      verify: `pytest tests/unit/test_window_binding.py`
- [x] P7f.2 vertical sweeps: UP bound, DOWN still unbound — the asymmetry is the decision.
      The old "both unbound" rested on `neg-idle-motion`, which ADR-0011 invalidated. What survives
      is the human argument, and it is about DOWN only: hands fall, so a downward sweep is often
      involuntary; there is no involuntary fast UPWARD sweep. An overview toggle is also the
      cheapest thing to get wrong — it shows you your windows and the next sweep closes it.
      verify: synthetic swipe_up -> ShowOverview, swipe_down -> {} (at 0.8s; the 0.4s generator
      default is shorter than the 550ms window and fails for horizontal sweeps too)
- [x] P7f.3 `linear_swipe` gained up/down + `swipe_up`/`swipe_down` generators — the corpus had no
      vertical fixture at all, so the y-sign was unverifiable. Confirmed empirically: image y grows
      downward, the mirror is horizontal only, so physical UP is NEGATIVE vy (measured -2.19).

## Done — P7g: the downward sweep suspends the machine

- [x] P7g.1 `Capability.SYSTEM_SUSPEND` + `PowerSink` port + `logind_power.LogindPowerSink`
      Chosen over synthesising KEY_SLEEP: a keycode only suspends if something happens to be
      listening, and that CANNOT be verified without actually sleeping the machine. logind answers
      `CanSuspend` first, so availability is checked without triggering anything. No root needed;
      polkit grants suspend to an active local session. `interactive=False` so it can never leave
      an invisible password prompt behind the overview.
      verify: `logind_power.available()` -> (True, ''); `pytest tests/unit/test_window_binding.py`
- [x] P7g.2 `Suspend` intent, bound to the DOWN sweep. `journal.inverse` returns None for it —
      a sleeping machine cannot be gestured awake, and an Undo that claimed otherwise would lie.
      Null/Recording power sinks added so no test can ever suspend the machine running CI.
      verify: corpus check — 0 fixtures produce Suspend; `make ci` 376 passed

## Now — V2 gate and beyond

- [ ] **The DOWN binding is the riskiest thing in the system and is UNMEASURED.** Down is the
      direction hands move involuntarily — falling back to the desk, or dropping at the end of any
      other gesture. No real fixture fires it today, but the corpus has no sound negative with an
      actively moving hand (ADR-0011), so "0 false fires" here means "untested", not "safe".
      If sleep ever fires on its own, suspect this first; the levers are `gross.speed` and
      `arbitration.enter_fraction.gross`.
      verify: replacement negative fixture produces 0 Suspend intents

- [ ] **The upward binding is UNMEASURED against real negatives.** `neg-idle-motion` now fires a
      ShowOverview as well as a SwitchWindow — but that is the fixture ADR-0011 invalidated, and it
      is the corpus's ONLY negative with an actively moving hand. So there is currently no sound
      evidence either way about how often an upward sweep false-fires in real use. Recording the
      replacement negative is what closes this.

- [ ] **Vertical sweeps: re-open the decision.** `modes/gross.py` justifies leaving them unbound
      with "binding them made `neg-idle-motion` produce two spurious maximises". ADR-0011 has since
      shown that fixture contains real swipes, so that evidence no longer supports the conclusion.
      The human argument (vertical hand motion is largely involuntary) may well still hold — but it
      is now unmeasured. Re-test after the replacement negative is recorded.
      verify: bind up/down, regenerate goldens, diff against a corpus that is actually negative

- [ ] **RE-RECORD the missing negative** — `neg-idle-motion` was the corpus's only fixture with an
      actively moving hand, and it turned out to be swipes. The gross thresholds are now defended by
      `hover-at-threshold` ALONE. Needs: in-frame hand activity that never becomes a horizontal
      sweep — gesturing while talking, adjusting glasses, reaching for a mug at desk height.
      verify: fires 0 gross intents at speed=1.8/coherence=0.70, with hand present >80% of frames

- [ ] the 8-hour daily-driver session (needs the logout)
- [ ] bind the grammar's compound actions to real intents (currently recorded, not executed)
- [ ] `SetParameter` talks to PulseAudio rather than emitting volume keys

## Blocked

- [x] PANIC resolved — ADR-0010. Arms extended gives 100% two-hand detection; the real fixture
      tracks 98% and BOTH detection paths fire on it. Constraint: the gesture needs your hands
      well inside the frame, which is arguably correct for a deliberate kill switch.
- [x] `swipe-right-real` re-recorded — 5/5 swipes detected. The first take failed because it was a
      symmetric back-and-forth wave: the return stroke cancelled the swipe. A gross gesture needs
      an ASYMMETRIC stroke (fast out, slow back), which is a real usability finding for the docs.

- [!] P2.6 Real gesture fixtures — I cannot perform gestures in front of the camera. The corpus is
      currently synthetic (analytic kinematics, clearly marked in each sidecar) plus one real
      `live-desk-6s` capture. `python main.py record <label> --seconds 10` is ready; record
      swipe-left, pinch-click, fist-hold and a genuine coffee-cup reach, then
      `python main.py golden --update` and review the diff.
- [x] P6.6 Extension VERIFIED end to end — `tools/verify_extension.sh` moves a real window.
      Fixed a real Mutter 50 bug on the way (`get_maximized` removed). ADR-0008.
- [!] P6.7 Not yet loaded in YOUR session — GNOME only scans extensions at startup, so this
      needs a log out / log in. Already installed and enabled:
      `~/.local/share/gnome-shell/extensions/gesture-os@anurag.local`
      Verify WITHOUT logging out: `tools/verify_extension.sh` (GNOME 50 removed `--nested`;
      it is `--devkit --virtual-monitor` now — ADR-0008)
      Until then `shell_ext.py` reports unavailable and the router degrades — by design.
- [!] P4.4 uinput cursor verification — blocked on the same privileged steps as P0.14.
      `python main.py run --effector uinput` works the moment they are done.

- [!] P0.13 AT-SPI pointer injection — **INCONCLUSIVE, needs a human looking at the screen.**
      `Atspi.generate_mouse_event` exists and returns without raising, but on Wayland that is
      frequently a silent no-op and the call has no return value to tell the difference. The
      pointer cannot be read back (`org.gnome.Shell.Eval` returns `(false, '')`, correct for
      GNOME 50). See ADR-0003.
      unblock: `./venv/bin/python tools/spikes/p0_13_atspi_pointer.py` and watch the cursor
- [!] P0.14 uinput `Super+Left` spike — blocked on two privileged one-time steps:
      `sudo apt install -y python3-evdev`, then the udev rule + `usermod -aG input` in ADR-0003,
      then a full logout/login.
      Neither blocks P1-P3: the engine develops against null/recording backends, and the choice
      is only needed at P4.

## Gated — V3 (do not start)

**gate:** every box under "V2 exit checklist" is checked.

- [ ] V3.E NL gesture binding (Jev point E) — config-time only, zero realtime surface
- [ ] V3.A app-aware remapping (Jev point A — provider already built in P1)
- [ ] V3.chord bimanual chording (local, no Jev)
- [ ] V3.C adaptive radial menu (Jev point C)
- [ ] V3.G semantic text selection (Jev point G)
- [ ] V3.D teach-by-demonstration (Jev point D)
- [ ] V3.B ray-cast tiling (Jev point B — the only one needing the Shell extension)
- [ ] V3.slider parametric sliders (local)
- [ ] V3.grammar gesture grammar (local)

## V2 exit checklist (the gate)

- [ ] 8-hour daily-driver session with zero panic activations — **blocked on uinput (re-login)**
- [x] `rest-60s` and `coffee-cup`: 0 unintended transitions (plus neg-typing, neg-reach, live-desk)
- [x] glass-to-cursor measured and recorded in README (~64ms; ADR-0006 — camera-limited)
- [x] panic → all effectors released, independent of `step()` (`tests/unit/test_watchdog.py`)
- [~] every intent has a working undo — TileWindow is honestly un-undoable until P6 gives us
      the window's previous geometry; everything else inverts
- [x] `make ci` green (247 tests); `golden` 14/14
- [x] runs end-to-end with `--offline` (every CI test uses the rules provider)

Remaining: the daily-driver session, which needs a real cursor, which needs the re-login.

## Deferred (decided, not forgotten)

- **Per-frame Jev** — permanently forbidden. ADR-0001, lint-enforced.
- **GNOME Shell extension** → P6, after V2 ships. GNOME's own keybindings cover every gross gesture
  the scope doc names; the extension only buys arbitrary-rectangle placement for ray-cast tiling.
- **Absolute pointer positioning** → not needed until ray-cast tiling. `EV_ABS`/`INPUT_PROP_DIRECT`
  makes libinput treat the device as a touchscreen. ADR-0002.
- **Cross-platform (Windows/macOS)** → out of scope. Additive under `effectors/backends/` if ever.
- **Depth/IR sensors** → explicit non-goal in the scope doc.

## Done

| date | id | task |
|------|----|------|
| 2026-09-18 | P7c  | bimanual chording, parametric slider, gesture grammar, `teach` |
| 2026-09-18 | P7.4 | **Jev point D live** — prompt reframed after the noul saturated at 1.00 |
| 2026-09-18 | P7.3 | **Jev point G live** — span arithmetic in code, span CHOICE from Jev |
| 2026-09-18 | P7.6 | context service — the Jev layer finally reaches the engine |
| 2026-09-18 | cal  | real-fixture calibration: ADR-0009 (window), ADR-0010 (panic framing) |
| 2026-09-18 | P7.1 | **Jev point C live** — prefetch, after a 250ms budget timed out on every call |
| 2026-09-18 | P7.2 | **Jev point E live** — invalid bindings structurally impossible |
| 2026-09-18 | P7.0 | closed action catalogue (20 actions) |
| 2026-09-18 | P6.6 | extension verified moving a real window; ADR-0008 corrects `--nested` |
| 2026-09-18 | P6.4 | **Jev point B live** — found + fixed a cache key that broke its own premise |
| 2026-09-18 | P6.3 | shell_ext client + fake-D-Bus contract tests |
| 2026-09-18 | P6.1 | GNOME Shell extension (GJS, ESM, versioned D-Bus) |
| 2026-09-18 | P5.6 | calibration wizard; corrected ADR-0007's own conclusion |
| 2026-09-18 | P5.5 | **Jev point F live** — misfire post-mortem, numbers rendered to words |
| 2026-09-18 | P5.4 | HUD with dwell preview; layer-shell degrades to terminal |
| 2026-09-18 | P5.3 | independent panic watchdog |
| 2026-09-18 | P5.1 | pose template library + record-pose |
| 2026-09-18 | P4.3 | `run` end to end on the real camera; uinput backend written |
| 2026-09-18 | P3.8 | 206 tests; property tests found the 12fps window bug |
| 2026-09-18 | P3.5 | pure `step()` + four hysteresis layers; 11/11 golden streams |
| 2026-09-18 | P3.2 | feature extraction, scale/translation invariant |
| 2026-09-18 | P2.5 | 11-fixture corpus + golden intent streams |
| 2026-09-18 | P2.1 | mediapipe camera source; ADR-0005 and ADR-0006 from the measurements |
| 2026-09-18 | P1.12 | P1 EXIT — jev / cache / rules all verified end to end |
| 2026-09-18 | P1.11 | calibration: 113-row corpus; ≥0.85 bucket 102/104. Found + fixed a confidently-wrong rules bug |
| 2026-09-18 | P1.10 | points/a_app_context.py + points.yaml (prompt AND fallback table) |
| 2026-09-18 | P1.9 | decision/broker.py — the only provider-calling thread; firewall test green |
| 2026-09-18 | P1.8 | decision/sanitize.py — 10 tests incl. a live-verified injection case |
| 2026-09-18 | P1.7 | composite.py — Caching/Budgeted/Fallback; 16 tests, one a cache regression |
| 2026-09-18 | P1.6 | backends/typesafe.py — TypeSafeProvider; 6 live tests green |
| 2026-09-18 | P1.5 | backends/rules.py + replay.py |
| 2026-09-18 | P1.4 | decision/questions.py + provider.py |
| 2026-09-18 | P1.3 | effectors/backends/atspi_focus.py — window:activate |
| 2026-09-18 | P1.2 | app/naming.py — focus cache keys (moved down a layer; linter caught it) |
| 2026-09-18 | P1.1 | SPIKE: 12 real titles, 11/12; found the 375ms latency that reshaped point C |
| 2026-09-18 | P0.15 | P0 EXIT — `replay --synthetic swipe_left` runs end to end; `make ci` green |
| 2026-09-18 | P0.12 | tools/check_no_magic_numbers.py + 8 tests |
| 2026-09-18 | P0.11 | .importlinter — 6 contracts, incl. the Jev firewall |
| 2026-09-18 | P0.10 | app/cli.py + runtime/pipeline.py + main.py; doctor is phase-aware |
| 2026-09-18 | P0.9 | perception source protocol, NDJSON format, 10 synthetic generators |
| 2026-09-18 | P0.8 | null + recording backends for all six ports |
| 2026-09-18 | P0.7 | effectors/ports.py — six capability-scoped ports |
| 2026-09-17 | P0.6 | app/config.py loader — 12 validation tests, incl. Schmitt-pair guard |
| 2026-09-17 | P0.5 | app/intents.py — Intent objects with capability declarations |
| 2026-09-17 | P0.4 | app/types.py — cross-layer vocabulary, 7 tests |
| 2026-09-17 | P0.3 | requirements.txt, .gitignore, .env.example, Makefile |
| 2026-09-17 | P0.2 | doc trio + scope copied to docs/scope.md |
| 2026-09-17 | P0.1 | repo tree, package __init__ files, git init |
