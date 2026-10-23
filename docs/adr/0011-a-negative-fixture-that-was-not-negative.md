# ADR-0011 — A negative fixture that was not negative

Status: accepted · 2026-09-18

## Context

After fixing the frame-grabber data race (ADR-0006 follow-up) and relaxing the GROSS enter guard
from `for_all_frames` to `for_enter_fraction` (ADR-0009), a live recording of a deliberate swipe
(`live-swipe-check`) finally produced a `SendToWorkspace`. One negative fixture started firing with
it: `neg-idle-motion`.

The obvious response was to tune. A sweep over `enter_fraction × gross.speed × gross.coherence`
against 5 positives and 14 negatives found three "clean" combinations:

```
 frac  speed   coh | detected | false
 0.80    1.8  0.80 |    4/5   |   0
 0.85    1.8  0.80 |    4/5   |   0
 0.90    1.8  0.70 |    4/5   |   0
```

Every clean combination detected 4/5, and the missing positive was **always `live-swipe-check`** —
the only fixture recorded from a real hand after the grabber fix, i.e. the one that represents what
the user actually does. Every combination that caught it fired on `neg-idle-motion`. The knob could
trade one for the other and nothing else.

## Decision

Measure the two fixtures instead of tuning between them.

| | frames | hand | speed p50 / p90 / max | coherence p50 / p90 | x-travel |
|---|---|---|---|---|---|
| `live-swipe-check` | 177 | 165 | 0.74 / 6.13 / 10.35 | 0.65 / 0.99 | 0.788 |
| `neg-idle-motion`  | 179 | 169 | 0.94 / 6.56 / 13.44 | 0.91 / 0.99 | 0.562 |

**`neg-idle-motion` scores higher than the deliberate swipe on every feature the gross guard
reads.** Its longest run above `(speed ≥ 1.8, coherence ≥ 0.7)` is 13 frames against the swipe's 7,
sitting between `live-swipe-check` (7) and `swipe-left-real` (14). The x-trace is decisive:

```
neg-idle-motion  x: ...666666666654211246666666665555444322111.12346666666655544
```

The palm sweeps 0.66 → 0.11 → 0.66, twice, over 0.562 of frame width. Those are swipe trajectories.
The fixture does not contain what its name claims, so no threshold can separate the two — there is
nothing there to separate. The three "clean" results were fitting to a bad label, and the price was
the only positive that matters.

`neg-idle-motion` is therefore **unlabelled for `gross`** in `tools/calibrate_thresholds.py` rather
than suppressed by tuning. `gross.speed` and `gross.coherence` stay at 1.8 / 0.70; with the bad
fixture excluded the calibrator independently recommends 1.81 / 0.71, which is the same answer.

## Consequence — the corpus now has a hole, and it is load-bearing

`neg-idle-motion` was the **only** negative containing an actively moving hand:

| negative | frames | hand frames | speed p90 | x-travel |
|---|---|---|---|---|
| `coffee-cup`, `live-desk-6s`, `neg-typing`, `neg-reach` | 87–148 | **0** | — | — |
| `rest-60s`, `pose-hold` | 60–1800 | all | 0.15–0.27 | ~0.000 |
| `hover-at-threshold` | 90 | 90 | 3.99 | 0.106 |
| `neg-idle-motion` | 179 | 169 | 6.56 | 0.562 |

Typing and reaching happen below the camera and contain no hands at all, so they constrain nothing.
`hover-at-threshold` is the only surviving negative that is genuinely hard — a hand moving **fast
without going anywhere** (p90 speed 3.99, travel 0.106) — and it is the shape the replacement needs.

**The gross thresholds are currently defended by one fixture.** Re-record the missing negative —
in-frame hand activity that never becomes a horizontal sweep: gesturing while talking, adjusting
glasses, reaching for a mug at desk height — before trusting them further.

## What this cost, and the lesson

Three rounds of threshold sweeps produced results that all looked like wins and all were wrong,
because the corpus asserted something false. The sweep was the wrong instrument: it can only trade
error between fixtures, never tell you a fixture is lying. **Plot the trajectory before tuning
against a label.** A single x-trace answered in one command what three sweeps could not.

This is the second time in this project that a measurement was trusted past its validity — the first
was the 15fps camera figure taken in a near-dark room (ADR-0006).
