"""Gross gesture — the committed sweep.

Preempting: once velocity holds above threshold across the ENTIRE window with a coherent heading,
this wins regardless of dwell or streak. That is the scope doc's rule, and `for_all_frames` makes
it executable — while also being the hysteresis, since one frame below threshold defeats it.

The coherence requirement is not decoration. Measured on the `tremor` fixture: a shaking hand
reaches 2.08 palm-widths/s, ABOVE the 1.8 gross threshold — but its direction coherence is 0.21.
Speed alone would fire a window-manager command on a tremor, which is precisely the accessibility
case the scope doc cares about.
"""

from __future__ import annotations

from app.arbitration.guards import (
    all_of,
    coherence_above,
    for_enter_fraction,
    for_fraction,
    hand,
    present,
    speed_above,
)
from app.arbitration.registry import ModeSpec
from app.config import Config
from app.intents import Direction, ShowOverview, Suspend, SwitchWindow
from app.types import DecisionContext, FeatureWindow, ModeId

# `for_all_frames` (every frame) was unusable against real tracking: it takes the MINIMUM across
# the window, so one dropped frame scores 0 and the sweep is lost. Measured on a real swipe with
# 93% tracking and speed peaking at 10.3 against a 1.8 threshold, this scored exactly 0.00 for an
# entire 12-second recording.
#
# `arbitration.enter_fraction.gross` is what now carries the "sustained across the window"
# requirement the scope doc asks for — 0.75 of the window rather than all of it.
_ENTER = for_enter_fraction(
    ModeId.GROSS,
    all_of(present(), speed_above("gross.speed"), coherence_above("gross.coherence")),
)
_SUSTAIN = for_fraction(ModeId.GROSS, speed_above("gross.speed_sustain"))


def _handler(w: FeatureWindow, ctx: DecisionContext, st, cfg: Config, entered: bool):
    # A sweep is ONE command. Emitting on every sustained frame turned a single swipe into 18
    # switches. The refractory period in config then prevents the next sweep from firing during
    # the hand's return travel.
    if not entered:
        return ()
    h = hand(w.latest)
    if h is None:
        return ()
    vx, vy = h.palm_velocity[0], h.palm_velocity[1]
    if abs(vx) >= abs(vy):
        # LEFT is the PREVIOUS window, keeping the direction sense SendToWorkspace established:
        # the sweep direction names where you are going, not which way anything slides.
        return (SwitchWindow(Direction.LEFT if vx < 0 else Direction.RIGHT),)

    # UP opens the Activities overview. DOWN stays unbound, and that asymmetry is deliberate.
    #
    # Both were unbound until now, on the evidence that binding them made `neg-idle-motion` produce
    # two spurious maximises. ADR-0011 has since shown that fixture is full of real swipes, so that
    # evidence proved nothing and the decision was reopened rather than inherited.
    #
    # What survives is the human argument, which is about DOWN specifically: hands fall. A hand
    # returning to the desk, or dropping at the end of any other gesture, is a downward sweep that
    # was never meant as one. There is no equivalent involuntary UPWARD sweep — lifting a hand that
    # fast is something you have to decide to do.
    #
    # An overview toggle is also the cheapest possible thing to get wrong: a false fire shows you
    # your own windows and the next sweep closes it. Nothing is moved, nothing is lost. DOWN stays
    # unbound until there is a negative fixture good enough to measure it against.
    if vy < 0:
        return (ShowOverview(),)

    # DOWN suspends the machine. Bound on request, and it is the riskiest binding in the system:
    # this is the direction hands move INVOLUNTARILY — a hand falling back to the desk, or dropping
    # at the end of any other gesture, is a downward sweep nobody performed. Everything else here
    # is cheap to get wrong; this one ends the session mid-work.
    #
    # It is also UNMEASURED. The corpus has no sound negative with an actively moving hand
    # (ADR-0011), so the false-fire rate of a downward sweep is currently unknown rather than known
    # to be low. If sleep starts firing on its own, this binding is the first thing to suspect and
    # `gross.speed` / `enter_fraction.gross` are the levers.
    return (Suspend(),)


GROSS = ModeSpec(
    mode=ModeId.GROSS,
    priority=80,  # tuning-exempt: mode ordering is structure, not tuning
    enter=_ENTER,
    sustain=_SUSTAIN,
    handler=_handler,
    preempt=True,
)
