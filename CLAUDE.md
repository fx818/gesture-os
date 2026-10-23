# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- 12-rule template — do not remove -->
## Development Rules

These rules apply to every task in this project unless explicitly overridden.
Bias: caution over speed on non-trivial work. Use judgment on trivial tasks.

## Rule 1 - Think Before Coding
State assumptions explicitly. If uncertain, ask rather than guess.
Present multiple interpretations when ambiguity exists.
Push back when a simpler approach exists.
Stop when confused. Name what is unclear.

## Rule 2 - Simplicity First
Minimum code that solves the problem. Nothing speculative.
No features beyond what was asked. No abstractions for single-use code.
Test: would a senior engineer say this is overcomplicated? If yes, simplify.

## Rule 3 - Surgical Changes
Touch only what you must. Clean up only your own mess.
Do not improve adjacent code, comments, or formatting.
Do not refactor what is not broken. Match existing style.

## Rule 4 - Goal-Driven Execution
Define success criteria. Loop until verified.
Do not follow steps. Define success and iterate.
Strong success criteria let you loop independently.

## Rule 5 - Use the model only for judgment calls
Use me for: classification, drafting, summarization, extraction.
Do NOT use me for: routing, retries, deterministic transforms.
If code can answer, code answers.

## Rule 6 - Token budgets are not advisory
Per-task: 4,000 tokens. Per-session: 30,000 tokens.
If approaching budget, summarize and start fresh.
Surface the breach. Do not silently overrun.

## Rule 7 - Surface conflicts, do not average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Do not blend conflicting patterns.

## Rule 8 - Read before you write
Before adding code, read exports, immediate callers, shared utilities.
Looks orthogonal is dangerous. If unsure why code is structured a way, ask.

## Rule 9 - Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that cannot fail when business logic changes is wrong.

## Rule 10 - Checkpoint after every significant step
Summarize what was done, what is verified, what is left.
Do not continue from a state you cannot describe back.
If you lose track, stop and restate.

## Rule 11 - Match the codebase conventions, even if you disagree
Conformance > taste inside the codebase.
If you genuinely think a convention is harmful, surface it. Do not fork silently.

## Rule 12 - Fail loud
Completed is wrong if anything was skipped silently.
Tests pass is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.

---

## Commands

```bash
source venv/bin/activate

make ci          # lint + all camera-free, network-free tests. This is the gate.
make doctor      # check this machine: camera, uinput, AT-SPI, mediapipe, Jev key
make golden      # regenerate golden intent streams — ALWAYS review the diff
make ci-live     # re-run Jev points against the live API, diff vs fixtures/judgment/

python main.py record swipe-left       # record a landmark fixture
python main.py replay <fixture> --viz  # replay with skeleton overlay
python main.py judge app-context --app code --title "engine.py — VS Code"
python main.py run                     # the real thing
python main.py run --offline           # Jev disabled, rules provider only
```

## Architecture

```
camera ──► perception ──► features ──► arbitration ──► intents ──► routing ──► effectors
             (impure)      (PURE)       (PURE)                      (impure)    (impure)
                                           ▲
                                           │ DecisionContext (frozen input, carries age_ms)
                                           │
                            context/store ◄┴─ decision/broker ──► Jev   (own thread, never the loop)
```

**Three axes of variability, and they are the only places impurity is allowed:**

| Axis | Port | Backends |
|---|---|---|
| Where landmarks come from | `LandmarkSource` | mediapipe camera / file replay / synthetic / subprocess |
| Where effects go | `PointerSink`, `KeySink`, `FocusSource`, `WindowManager`, `OverlaySink` | uinput / AT-SPI / shell-ext / null / recording |
| Where judgment comes from | `JudgmentProvider` | TypeSafe (Jev) / local rules / recorded replay |

Everything between those edges is a pure deterministic function of data. That is what makes the
whole brain of the product testable from files on disk with no camera and no network.

### Two invariants that are easy to break and expensive to debug

1. **Clock is data.** Nothing in `features/` or `arbitration/` may call `time.monotonic()`.
   All time comes from `frame.t_ms`. This is what makes replay bit-reproducible.
2. **Jev is never on the per-frame path.** Enforced four ways: `lint-imports` forbids
   `arbitration → decision`; `JudgmentBroker` owns the only provider-calling thread;
   `DecisionContext` is a frozen *input* to `step()`; and a CI test asserts
   `broker.calls_from_loop_thread == 0`. See ADR-0001.

### Where things live

| Path | Owns |
|---|---|
| `app/types.py` | the cross-layer vocabulary. Imports nothing of ours. |
| `app/arbitration/engine.py` | `step()` — pure. The core deliverable. |
| `app/arbitration/guards.py` | composable guard combinators; guards return confidence, not bool |
| `app/decision/points/` | one file per Jev integration point (A–G) + its rules fallback |
| `config/default.toml` | every numeric threshold. Lint-enforced: no magic numbers in `arbitration/`. |
| `config/judgment/points.yaml` | every Jev instruction + confidence threshold. The human-review surface. |
| `fixtures/golden/` | expected intent streams. A behavior change = a reviewable diff. |

### Adding things

- **A new gesture mode:** one file in `app/arbitration/modes/` + one line in its `__init__.py`.
  `engine.py` never changes.
- **A new Jev point:** one file in `app/decision/points/` (question set + rules fallback, reviewed
  together) + one entry in `config/judgment/points.yaml`. Bump its `rev` on any prompt edit —
  `rev` is part of the cache key, so editing a prompt auto-invalidates the cache.
- **A new effector backend:** implement the port, declare `capabilities()`. The router degrades on
  missing capability rather than crashing.

## Environment

| Variable | Purpose |
|---|---|
| `TYPESAFE_API_KEY` | Jev access. Absent ⇒ rules-only provider, product still works. |
| `GESTURE_OS_OFFLINE` | `1` forces the rules provider even with a key present |
| `TYPESAFE_DEFAULT_MODEL` | defaults to `jev-latest` |

Target platform is **Ubuntu 26.04 / GNOME 50 / Wayland**. X11 tools (xdotool, wmctrl) do not work
here. Input injection goes through `/dev/uinput`; focus reads through AT-SPI; arbitrary window
placement needs the GNOME Shell extension in `extension/` (P6).

The venv **must** be created with `--system-site-packages` — `gi.repository.Atspi` and `evdev` come
from system packages, not PyPI.
