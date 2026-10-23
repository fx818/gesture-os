"""Parametric slider — a gesture that carries a continuous value rather than firing an event.

The scope doc's example: pinch distance to volume, wrist rotation to zoom, hand height to
brightness. What makes this a distinct mode rather than a variant of precision is that it needs its
own smoothing: a parameter being *set* must not jitter, and the One Euro filter that makes a cursor
feel responsive is tuned for a different job.

Only armed under a chord. An unmodified pinch is a click (precision mode) — the same physical
gesture meaning two things is exactly what chording is for, and without the modifier every click
would also nudge the volume.
"""

from __future__ import annotations

from app.arbitration.guards import (
    all_of,
    for_fraction,
    hand,
    in_chord,
    present,
)
from app.arbitration.registry import ModeSpec
from app.config import Config
from app.intents import SetParameter
from app.types import DecisionContext, FeatureWindow, ModeId

# The pose that arms slider mode. Recorded by the user like any other; if they have not recorded
# it, `in_chord` never matches and the mode simply never activates.
SLIDER_CHORD = "fist"

_ARMED = all_of(present(), in_chord(SLIDER_CHORD))


def _normalise(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _handler(w: FeatureWindow, ctx: DecisionContext, st, cfg: Config, entered: bool):
    h = hand(w.latest)
    if h is None:
        return ()
    # Pinch distance is already in palm widths, so the mapping is resolution- and
    # distance-independent without any calibration step.
    value = _normalise(
        h.pinch_thumb_index, cfg.precision.pinch_click_close, cfg.slider.pinch_max
    )
    return (SetParameter(name=cfg.slider.parameter, value=value),)


SLIDER = ModeSpec(
    mode=ModeId.SLIDER,
    priority=30,  # tuning-exempt: mode ordering is structure
    enter=_ARMED,
    sustain=for_fraction(ModeId.SLIDER, _ARMED),
    handler=_handler,
)
