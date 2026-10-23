# ADR-0007 — Thresholds tuned on synthetic data do not survive real hands

**Status:** accepted · 2026-09-18 · first real gesture fixture

## Finding

`fixtures/sessions/swipe-left-real.ndjson.gz` — 12 seconds of a person swiping left, 180 frames,
112 with a hand tracked. Feature profile against the thresholds the engine was carrying:

| | real swipe | synthetic `swipe_left` | threshold in config |
|---|---|---|---|
| palm speed p50 | **5.97** | 2.39 | `gross.speed` = 1.8 |
| palm speed p90 | **17.19** | 2.39 | |
| palm speed max | **53.81** | 2.39 | |
| coherence p50 | **0.80** | 1.00 | `gross.coherence` = 0.85 |

**91% of frames in a real swipe exceed the gross speed threshold.**

> **Correction (same day, after building `tools/calibrate_thresholds.py`):** I called this
> "not discriminating", and that was the wrong metric. What matters is not how many *positive*
> frames clear a threshold — ideally all of them do — but how many *negative* frames clear it.
> Measured across the labelled corpus: at `gross.speed = 1.8`, **94% of positive frames clear it
> and 2% of negative frames do.** That is a well-placed threshold, not a broken one. The alarm was
> unwarranted and the recommender's own answer is 1.73, i.e. essentially unchanged.
>
> The genuine finding survives, and it is the coherence one below.

And real motion is *less* straight than synthetic: coherence p50 is 0.80 against a 0.85 threshold.
The gesture fired anyway, because `for_all_frames` only needs the frames inside one 250 ms window
to agree — but the margin is thin in the wrong direction.

## Why the synthetic corpus was so far off

Two compounding reasons, and both were predictable in hindsight:

1. **Frame rate.** The generators run at 30 fps; this camera delivers 15 (ADR-0006). At half the
   rate a hand covers twice the distance between samples, so the same physical gesture reports
   double the palm-widths-per-second.
2. **I invented the speed.** `linear_swipe(speed=2.4)` was a number I chose to sit comfortably
   above a threshold I had also chosen. It was never a measurement of anything. A real swipe is
   3-20x faster.

The synthetic corpus remains the right tool for what it was built for — deterministic kinematics,
pathological cases a human cannot perform on demand, and decoupling the engine phase from
recording. It is not a substitute for measuring a person.

## What did change

`gross.coherence`: **0.85 -> 0.70**.

A real swipe has a 25th-percentile direction coherence of 0.70; my synthetic generator produced a
perfect 1.00, because a programmatic straight line is straighter than any arm. At 0.85 a real
swipe was clearing by the margin of a single window. Negatives sit at 0.23 median, so the
separation remains wide — this buys robustness without costing discrimination.

That is the whole legitimate yield of one real fixture, and it is worth having.

## Decision

**Do not retune anything else from this single fixture.** One positive sample fits a threshold to
itself; it says nothing about what must NOT fire, which is where the thresholds actually come from.

What is needed before retuning, deliberately mirroring the Jev point A calibration in
`docs/verification/p1-calibration.md`:

- real **negatives**: typing, reaching for a cup, scratching, gesturing while talking
- real **precision** motion: slow deliberate pointing by the same person
- a second person, since hand size and gesture vigour vary enormously

Then set `gross.speed` and `gross.coherence` from the separation between those distributions,
exactly as `act_threshold` was set from the confidence buckets — and record the result.

## Interim

Thresholds are unchanged. The engine correctly detected 4 of ~5 real swipes with no false
positives in the same take, which is good enough to keep moving, and the numbers above are the
starting point for P5's calibration wizard rather than an excuse to guess again now.
