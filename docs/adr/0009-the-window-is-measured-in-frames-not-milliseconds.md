# ADR-0009 — The arbitration window's real unit is frames of evidence, not milliseconds

**Status:** accepted · 2026-09-18 · measured end to end on real fixtures

## What happened

The first corpus of real negative data — a person moving their hand around in frame the way anyone
does while thinking or talking, 166 tracked frames — made the engine fire **two spurious workspace
switches and three macro entries**. That is the scope doc's #1 listed risk, reproduced.

The obvious response was to raise `gross.speed` and `gross.coherence`. It does not work:

```
  speed  coh  | gestures detected | false fires
    1.8  0.70 |       3/4         |      2
    2.5  0.70 |       1/4         |      2
    3.5  0.94 |       1/4         |      1
    5.0  0.94 |       1/4         |      1
```

Every pair either kept the false fires or destroyed detection. **Speed and coherence cannot
separate these signals**, and the measurements say why:

| | real swipe | casual movement |
|---|---|---|
| speed p50 | 5.97 | 0.95 (p90 **6.56**) |
| direction coherence p50 | 0.80 | **0.91** |

Casual movement is *more* direction-coherent than a deliberate swipe. The coherence threshold was
discriminating nothing.

## The actual cause

At 15fps, a 250ms window contains **3-4 frames**. Over three samples almost any motion is
straight, fast and coherent — there is simply not enough evidence in the window to tell a
committed sweep from an arm moving about.

The scope doc specifies a "~250ms sliding window", and that is correct **at the 30fps it assumes**,
where the same window holds 7-8 frames. This camera delivers 15.3fps (ADR-0006), so the window
silently carried half the evidence it was designed to.

Sweeping the span, with thresholds untouched:

```
  span 250ms -> 3/4 detected, 2 false fires
  span 400ms -> 3/4 detected, 1 false fire
  span 550ms -> 3/4 detected, 0 false fires
```

## Decision

`window.span_ms = 550`, and the reasoning is recorded because the number is **camera-specific and
will be wrong on other hardware**. The parameter that actually matters is frames of evidence
(~8); milliseconds are a proxy that is only valid at a fixed frame rate.

The honest long-term fix is to derive the span from observed frame rate at runtime, so the window
always holds ~8 frames whatever the camera does. Deferred rather than done, because it needs a
second camera to validate against and there is exactly one here.

## Cost

A gross gesture now takes 550ms of sustained motion to confirm rather than 250ms. That is real
added latency on window commands, and it is the price of not firing them by accident. Precision
mode is unaffected — it acts on the latest frame, not on the window.

## What this says about the method

Three rounds of threshold tuning produced nothing, because I was tuning the wrong parameter. What
found it was measuring **what the engine emits** rather than what the features look like:
`calibrate_thresholds.py` compared per-frame distributions and cheerfully reported that only 4% of
negative frames exceeded the threshold — while the engine was firing real commands on the same
fixture. `sweep_thresholds.py` runs the actual pipeline and counts actual intents, and that is the
only number that meant anything.

The remaining miss, `swipe-right-real`, is a data-quality problem rather than a threshold one: that
take only tracked 35% of its frames, and a window requiring sustained evidence cannot survive that.
Re-record it in better conditions before reading anything into it.
