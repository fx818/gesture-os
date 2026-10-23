"""Precision — the cursor.

Index extended relative to the other fingers, palm moving slowly. The only sub-50ms path in the
system, and inherently one-handed, which is why `perception.max_hands` defaults to 1 (ADR-0005).

`index_extension` is measured RELATIVE to the other fingertips, so an open flat hand — which has a
long index too — does not read as pointing.
"""

from __future__ import annotations

from app.arbitration.guards import (
    Guard,
    all_of,
    for_fraction,
    hand,
    index_extended,
    present,
    speed_below,
)
from app.arbitration.registry import ModeSpec
from app.config import Config
from app.intents import Button, ButtonPress, MoveCursor
from app.types import DecisionContext, FeatureWindow, ModeId

_ENTER: Guard = all_of(
    present(),
    index_extended("precision.index_extension"),
    speed_below("precision.max_palm_speed"),
)

# Sustain tolerates a minority of bad frames: a single dropped tracking frame mid-drag must not
# drop the cursor.
_SUSTAIN: Guard = for_fraction(
    ModeId.PRECISION, all_of(present(), speed_below("precision.max_palm_speed_sustain"))
)

_PIXELS_PER_PALM_WIDTH = 900.0  # tuning-exempt: unit conversion, calibrated per user in P5


def _handler(w: FeatureWindow, ctx: DecisionContext, st, cfg: Config, entered: bool):
    h = hand(w.latest)
    if h is None or len(w.frames) < 2:  # tuning-exempt: a delta needs two samples
        return ()

    prev = w.frames[-2]  # tuning-exempt: previous frame index
    prev_hand = prev.right or prev.left
    if prev_hand is None:
        return ()

    # Relative deltas from the FILTERED centroid — the filter exists to smooth the cursor
    # (ADR-0002 explains why relative rather than absolute).
    dx = (h.palm_centroid[0] - prev_hand.palm_centroid[0]) * _PIXELS_PER_PALM_WIDTH
    dy = (h.palm_centroid[1] - prev_hand.palm_centroid[1]) * _PIXELS_PER_PALM_WIDTH

    intents: list = []
    if dx or dy:
        intents.append(MoveCursor(dx, dy))

    # Pinch as a Schmitt trigger, detected as an EDGE between consecutive frames rather than from
    # stored state. Two reasons: the handler is pure and has nowhere to put state, and the
    # physical pinch distance already carries the hysteresis — press on crossing below `close`,
    # release on crossing above `open`, and do nothing in the band between. A single threshold
    # chatters and produces repeated clicks on a held pinch (measured: 5 events for one pinch).
    now, before = h.pinch_thumb_index, prev_hand.pinch_thumb_index
    if before >= cfg.precision.pinch_click_close > now:
        intents.append(ButtonPress(Button.LEFT, True))
    elif before <= cfg.precision.pinch_click_open < now:
        intents.append(ButtonPress(Button.LEFT, False))
    return tuple(intents)


PRECISION = ModeSpec(
    mode=ModeId.PRECISION,
    priority=20,  # tuning-exempt: mode ordering is structure, not tuning
    enter=_ENTER,
    sustain=_SUSTAIN,
    handler=_handler,
)
