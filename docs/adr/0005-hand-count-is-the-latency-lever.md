# ADR-0005 — Track one hand by default; two hands is a mode, not a baseline

**Status:** accepted · 2026-09-18 · measured on this machine

## Measurement

MediaPipe HandLandmarker (float16 `.task`), 640×480 MJPG, CPU/XNNPACK, steady state after
15 warm-up frames. Inference only — capture adds ~8 ms.

| | hand present | hand absent |
|---|---|---|
| `num_hands=2` | **67.0 ms** | 33.5 ms |
| `num_hands=1` | **29.8 ms** | 39.9 ms |

Capture is not the problem: 7.7 ms p50, and the camera genuinely delivers 640×480 MJPG @ 30 fps.

Two things here contradicted my expectations, and both are recorded because they would otherwise
be re-derived later:

1. **Hand present is the expensive case, not hand absent.** With no hand in frame only the
   lightweight palm detector runs and finds nothing; once a hand is found, the full 21-landmark
   model runs per hand. I guessed the opposite and measured it.
2. **Resolution is not a lever.** 480×360 (23.6 ms) and 320×240 (26.9 ms) are no better than
   640×480 (24.6 ms) — MediaPipe rescales internally — and 320×240 measurably *hurts* detection
   reliability. The GPU delegate was worse on both counts: 27.6 ms and 7/45 detection vs 29/45.

## Consequence for the latency budget

The scope doc targets **<50 ms glass-to-cursor** for precision mode.

- `num_hands=2`, hand present: 67 + 8 = **75 ms**. Over budget before features, arbitration or
  injection have run. ~15 fps sustained, which is what `bench` reports end to end.
- `num_hands=1`, hand present: 30 + 8 = **38 ms**, leaving ~12 ms for the rest of the pipeline.
  Tight, but the target is reachable.

## Decision

**`perception.max_hands` defaults to 1.** Two-hand tracking becomes a mode that is switched on,
not the always-on baseline.

This falls out of the scope doc's own structure rather than fighting it. Precision mode is the
only sub-50 ms path in the system, and it is inherently one-handed — an index finger tracking a
cursor. Everything that genuinely needs two hands is a **discrete** gesture with a 250–500 ms
budget, where 75 ms is comfortably affordable:

- two-hand panic (both palms open, held)
- two-hand pinch-pull (show desktop)
- bimanual chording (left hand holds a modifier pose)

## What this implies for later phases

Escalating to `num_hands=2` requires rebuilding the landmarker, so it cannot happen per frame.
The workable shape, when bimanual features land in V3:

- run at `num_hands=1` while in Precision or Idle
- escalate on a cheap trigger — the palm detector reporting a second blob, or an explicit arming
  gesture — and stay escalated while any bimanual mode is active
- de-escalate after a timeout back in Precision/Idle

Panic is the awkward case: it is two-handed and must work instantly from any state. Mitigation is
that the watchdog detects "both palms open and still" from whatever landmark stream it has; with
one hand tracked it degrades to a single-palm-open-and-still trigger, which is a weaker but still
serviceable kill switch. Decide properly in P5 when panic is built; noted here so it is not
discovered then.

## Honesty note on the first measurement

The first `bench` run reported 87 ms p50 and I nearly wrote the 50 ms target off entirely. That
number was contaminated by model load and XNNPACK warm-up averaged into the median. `bench` now
excludes a configurable warm-up window and reports it separately. The lesson is in the tool, not
just in this document.
