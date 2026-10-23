# ADR-0002 — The pointer emits relative deltas, not absolute positions

**Status:** accepted · 2026-09-17

## Context

Mapping a hand position directly to a screen position is the intuitive design, and it was the
initial proposal. On Linux it requires registering the virtual device with `EV_ABS` axes and
`INPUT_PROP_DIRECT`.

At that point libinput classifies the device as a **touchscreen**, not a pointer: tap-to-click
semantics, no persistent cursor, no hover. That is a multi-day fight with input plumbing for a
property the product does not need.

## Decision

`PointerSink` exposes `move_rel(dx, dy)` only. Deltas are derived from fingertip *velocity* and
smoothed with One Euro.

## Consequences

- No screen-coordinate mapping, so no multi-monitor geometry problem in the MVP.
- Matches the mouse analogue users already have; acceleration feels familiar.
- Two implementation details the backend owns: accumulate the fractional remainder of sub-pixel
  deltas across frames (or slow motion is lost to `int()`), and either add a libinput quirk keyed
  on the device name or calibrate out libinput's own acceleration curve.
- Absolute positioning is needed only for ray-cast tiling, which is gated on the GNOME Shell
  extension anyway. Revisit then, not before.
