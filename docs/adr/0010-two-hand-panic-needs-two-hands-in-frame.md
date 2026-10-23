# ADR-0010 — The two-handed panic gesture is not reliably detectable on a laptop webcam

**Status:** **RESOLVED** — it was framing, and option 1 worked · 2026-09-18

> ## Resolution
>
> Option 1 (sit further back) fixes it completely. With arms extended so both hands sit well
> inside the frame: **115/115 frames two-handed, 100%** — against 3/71 when sitting at a normal
> working distance with hands close to the camera.
>
> A recorded panic gesture at that distance tracks **145/148 frames (98%)**, and both detection
> paths now fire on it: the engine enters PANIC and the independent watchdog fires too.
>
> The constraint is real but mild, and it is arguably correct for a deliberate kill switch: you
> have to raise both hands clearly, which is exactly the "unmistakable" property a panic gesture
> wants. Options 2 and 3 below are not needed.
>
> One further threshold was wrong and is now measured: see the note on `panic.max_speed` at the
> end.

## What happened

`perception.max_hands` was set to 1 on ADR-0005's recommendation (one hand costs ~30ms of
inference, two costs ~67ms). ADR-0005 flagged panic as "the awkward case" and deferred it.

It is not deferrable. With `max_hands=1` the two-handed panic gesture **cannot fire at all** — a
real 10-second recording of someone deliberately holding both palms up contains **zero** two-hand
frames, because only one hand was ever tracked. The kill switch the scope doc calls a hard
guarantee was, in the shipped configuration, incapable of triggering.

## The one-handed fallback was tried and rejected

Degrading to "one open palm held still" makes panic fire on ordinary activity: it triggered on the
`pinch-real` fixture, which is a hand held still in a fairly open shape — an extremely common
thing to do while thinking. A kill switch that goes off during normal work is worse than none,
because people turn it off.

## Setting max_hands=2 does not fix it either

With two-hand tracking enabled and a person deliberately holding both palms up to the camera:

```
frames by hand count:  {0 hands: 0,  1 hand: 68,  2 hands: 3}
```

**3 of 71 frames.** At laptop-webcam distance, both palms do not reliably fit in frame together —
the field of view is narrow and the user sits close. This is a framing and optics problem, not a
threshold or a model-configuration problem.

## Where this leaves the kill switch

`max_hands` is now **2** and `panic.require_both_hands` is **true**, so the gesture is at least
*possible*. It is not yet demonstrated to be *reliable*, and the numbers above say it probably is
not, on this hardware, at this sitting distance.

The latency argument for `max_hands=1` is also weaker than ADR-0005 made it look: ADR-0006
established the 50ms target is unreachable on this camera regardless (65ms sensor cadence), so the
extra inference is a smaller slice of an already-blown budget. Trading a working kill switch for
latency that cannot be banked is the wrong trade.

## Options, none yet chosen

1. **Sit further back / use an external webcam** with a wider field of view. Fixes it optically and
   costs nothing in software, but it is a constraint on the user rather than a solution.
2. **A one-handed panic that is not merely "open palm"** — something deliberately unusual, such as
   a rapid open-close-open, or an open palm held *above shoulder height*. Harder to trigger by
   accident than stillness, and detectable with one hand.
3. **Accept a non-gesture kill switch** — a keyboard chord, or simply moving the real mouse. Less
   elegant, and the scope doc asks for a gesture, but a reliable escape hatch beats an elegant one
   that does not fire.

Option 2 is the most promising and the most work. Option 1 should be tested first because it is
free and would tell us whether the gesture is sound and only the framing is wrong.

## Meanwhile

`runtime/watchdog.py` — the independent detector that bypasses the state machine entirely — shares
this limitation, because it reads the same feature frames. The redundancy it provides is real but
it is redundancy against *engine* failure, not against *detection* failure. Both paths depend on
seeing two hands.


## Postscript: `panic.max_speed` was wrong twice, for the same reason

With framing fixed, the engine's panic path *still* did not fire while the watchdog did. The two
paths disagreeing is what exposed the cause — a threshold, not the logic.

Measured across 145 real two-hand frames of a deliberately-held pose: max-hand speed **p50 0.33,
p75 0.59, p90 0.79**. The configured limit was **0.20**, and before that **0.08**. Both came from
synthetic fixtures whose hands were nearly motionless; neither was reachable by a person.

Now 0.60. A loose speed limit is safe here because **openness carries the discrimination** —
measured 1.00 against a 0.85 requirement — and openness is what a fist or a pinch fails. Verified:
no fixture other than the two panic ones triggers it.

This is the third threshold in this project set from synthetic data and refuted by real hands
(after `gross.speed` in ADR-0007 and `macro.max_speed`). The pattern is reliable enough to state as
a rule: **a threshold that has only ever been checked against a generator is a guess wearing a
number.**
