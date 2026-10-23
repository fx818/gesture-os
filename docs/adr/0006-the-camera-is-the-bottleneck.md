# ADR-0006 — The 50 ms target is unreachable on this hardware; the camera caps at 15 fps

**Status:** accepted — re-measured in adequate light, the cap holds · 2026-09-18

> ## Correction (2026-09-18, later)
>
> Every measurement below was taken in a **near-dark room**: a captured frame has a mean luminance
> of **8.9 / 255**. A hand held in frame is a black silhouette with no skin tone or texture, which
> is also why hand detection returned 0/40 across every configuration tried.
>
> Near-darkness is precisely the condition in which a webcam extends its exposure time and halves
> its frame rate. **The "hardware caps at 15 fps" conclusion is therefore not established.**
>
> The manual-exposure test below looked like it ruled this out, and it did not: in a black room a
> short exposure produces a black image, so "the frame rate did not improve" says nothing about
> what the sensor does with adequate light.
>
> **Re-measured (same day) with manual exposure at 200, which gives 12/12 hand detection:**
> frame interval p50 **65.7 ms**, sustained **15.5 fps**. Unchanged. The frame-rate cap is real
> hardware and survives the correction; only the *detection* failure was caused by darkness.
>
> So the headline conclusion stands — but it was very nearly accepted for the wrong reason, and
> the manual-exposure test that appeared to rule out lighting was worthless as run. Left in full
> above because the reasoning error is the more useful record.

## Finding

`/dev/video0` delivers a frame every **65 ms (15.3 fps)** and this does not move:

| format | requested | actual gap | fps |
|---|---|---|---|
| MJPG 640×480 | 30 fps | 65.4 ms | 15.3 |
| MJPG 1280×720 | 30 fps | 68.3 ms | 14.6 |
| MJPG 320×240 | 30 fps | 65.5 ms | 15.3 |
| YUYV 640×480 | 30 fps | 64.9 ms | 15.4 |

`CAP_PROP_FPS` reports 30. It is not honoured. Forcing manual exposure (`AUTO_EXPOSURE=1` with
`EXPOSURE` at 20 and 60) changes nothing — 65–66 ms throughout — so this is not the usual
auto-exposure-in-low-light story. The sensor or its driver is capped.

## Consequence

**The scope doc's <50 ms glass-to-cursor target cannot be met on this machine at any software
quality.** A new frame simply does not exist more often than every 65 ms. With zero processing,
the cursor could still only update at 15 Hz.

Realistic budget here:

```
sensor cadence      65 ms   (hard floor)
inference           34 ms   (num_hands=1, overlapped with the sensor wait — see below)
features + arbiter   ?      (P3; budgeted at <5 ms, measured in CI)
injection            ~1 ms
-----------------------------------------
end to end         ~65-70 ms
```

## What this changes

- **The README records the measured number, not the target.** The doc's 50 ms stays as the design
  goal for hardware that can deliver it.
- **`latency.precision_budget_ms` is not a promise the code can keep.** It stays in config as the
  aspiration, and `bench` reports the gap rather than asserting success.
- **Precision mode will feel like a 15 Hz mouse** on this camera. Whether that is usable is a
  question for real use in P4, not for a spreadsheet. The One Euro filter matters more, not less,
  because it now has to interpolate across 65 ms gaps.
- **Anyone reproducing this should check their own camera first.** `make bench` prints the sensor
  cadence; if it shows 33 ms, everything above is different for them.

## On the threaded capture

Capture was moved onto its own thread with a single-slot latest-frame buffer
(`_LatestFrameGrabber`), because the naive loop ran `cap.read()` and inference in series: block
~23 ms for the sensor, then spend ~40 ms inferring, during which the camera produced frames that
were discarded anyway.

**Honest accounting: it is currently a no-op on this machine.** Before and after both measure
64 ms per frame, because the 65 ms sensor cadence dominates either way. It is kept because:

- it becomes a real ~34 ms win the moment inference exceeds the sensor gap, which `num_hands=2`
  already does at 67 ms (ADR-0005)
- on a 30 fps camera it is the difference between 33 ms and 73 ms
- a single slot guarantees inference always runs on the *newest* frame; a queue would let the
  cursor lag by the whole backlog

## Measurement discipline this cost us

Three wrong conclusions were reached and discarded on the way here, all from measuring the wrong
thing:

1. "87 ms, hopeless" — model warm-up averaged into the median. `bench` now excludes it and reports
   it separately.
2. "capture is 7.7 ms, inference is the problem" — that was a tight read loop with no inference
   between reads, so `cap.read()` returned a buffered frame instead of waiting for the sensor.
3. "hand-absent is the expensive case" — the opposite is true (ADR-0005).

The per-stage timing now built into `bench` exists so the next such question takes a minute
instead of an hour.
