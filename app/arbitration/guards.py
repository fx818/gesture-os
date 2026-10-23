"""Guards as composable pure combinators.

A guard is `(window, ctx, cfg) -> confidence in [0, 1]`, deliberately not a boolean. Confidence is
what makes the Schmitt threshold layer possible: entering a mode needs a higher score than staying
in it, and a boolean has nowhere to put that distinction.

Each combinator is a few lines with its own unit test, which lets a mode be declared almost
entirely as data — reviewable by reading it, rather than by tracing control flow.

Nothing here reads config values by literal; every number arrives through `cfg`.
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

from app.config import Config
from app.types import DecisionContext, FeatureFrame, FeatureWindow, HandFeatures, ModeId

Guard = Callable[[FeatureWindow, DecisionContext, Config], float]

# A soft ramp width, as a fraction of the threshold. Turning a hard comparison into a ramp is what
# lets "just under" and "far under" score differently, which the streak and Schmitt layers then use.
_RAMP = 0.35  # tuning-exempt: shape of the ramp, not a threshold


def _ramp(
    value: float,
    threshold: float,
    *,
    above: bool,
    upper: float | None = None,
    lower: float = 0.0,
) -> float:
    """Confidence that `value` is above (or below) `threshold`, ramped rather than stepped.

    The ramp width is measured against the HEADROOM in the direction of interest, not against the
    threshold itself. That distinction is not cosmetic: direction coherence, openness and index
    extension are all bounded at 1.0, so with a 0.85 threshold there is only 0.15 of headroom.
    Sizing the ramp from the threshold gave a width of 0.30, which meant a *perfect* coherence of
    1.0 scored just 0.75 — below the 0.80 needed to enter GROSS. A committed swipe was
    mathematically incapable of firing.

    Pass `upper` for bounded quantities; leave it None for open-ended ones like speed.
    """
    if threshold == 0.0:
        return 1.0 if (value > 0.0) == above else 0.0

    if above:
        headroom = (upper - threshold) if upper is not None else abs(threshold)
    else:
        headroom = threshold - lower
    width = max(abs(headroom) * _RAMP, 1e-6)  # tuning-exempt: divide-by-zero floor

    delta = (value - threshold) if above else (threshold - value)
    return max(0.0, min(1.0, 0.5 + delta / (2.0 * width)))  # tuning-exempt: centred-ramp algebra


def hand(frame: FeatureFrame) -> HandFeatures | None:
    """The acting hand. Right if present, otherwise left — a left-handed user or a one-handed
    session must still work, and the scope doc's accessibility case demands it."""
    return frame.right or frame.left


# --- leaf guards -----------------------------------------------------------------------


def present() -> Guard:
    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        return 1.0 if hand(w.latest) is not None else 0.0

    return g


def speed_above(key: str) -> Guard:
    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        h = hand(w.latest)
        return 0.0 if h is None else _ramp(h.palm_speed, _lookup(cfg, key), above=True)

    return g


def speed_below(key: str) -> Guard:
    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        h = hand(w.latest)
        return 0.0 if h is None else _ramp(h.palm_speed, _lookup(cfg, key), above=False)

    return g


def coherence_above(key: str) -> Guard:
    """Bounded 0..1, so the ramp is sized against the headroom above the threshold."""

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        h = hand(w.latest)
        if h is None:
            return 0.0
        return _ramp(h.palm_dir_coherence, _lookup(cfg, key), above=True, upper=1.0)

    return g


def index_extended(key: str) -> Guard:
    """Bounded 0..1, so the ramp is sized against the headroom above the threshold."""

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        h = hand(w.latest)
        if h is None:
            return 0.0
        return _ramp(h.index_extension, _lookup(cfg, key), above=True, upper=1.0)

    return g


def openness_above(key: str) -> Guard:
    """Bounded 0..1, so the ramp is sized against the headroom above the threshold."""

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        h = hand(w.latest)
        if h is None:
            return 0.0
        return _ramp(h.openness, _lookup(cfg, key), above=True, upper=1.0)

    return g


def openness_below(key: str) -> Guard:
    """Bounded 0..1, ramped against the headroom below the threshold."""

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        h = hand(w.latest)
        if h is None:
            return 0.0
        return _ramp(h.openness, _lookup(cfg, key), above=False, lower=0.0)

    return g


def pose_matches(key: str, fallback: Guard) -> Guard:
    """Confidence that the current pose matches something in the user's library.

    The library is per-user and empty until poses are recorded, so `fallback` runs in that case —
    currently a coarse openness heuristic. It is a stand-in, and a bad one: it fires on any
    closed-ish hand rather than on a specific remembered pose. Record poses to replace it.
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        if cfg.poses.is_empty:
            return fallback(w, ctx, cfg)
        h = hand(w.latest)
        if h is None:
            return 0.0
        match = cfg.poses.best(h.joint_angles)
        # Ramp against the REALISTIC ceiling for this metric, not 1.0. Correlation tops out near
        # 0.45 for a genuine match, so a 1.0 ceiling made a true 0.33 match score 0.66 — below the
        # threshold needed to act on it.
        return _ramp(
            match.similarity,
            _lookup(cfg, key),
            above=True,
            upper=cfg.macro.template_similarity_max,
        )

    return g


def both_hands_open(open_key: str, speed_key: str) -> Guard:
    """The panic pose: open palm(s) held still.

    Requires BOTH hands only when `panic.require_both_hands` is set. It is off by default because
    `perception.max_hands` is 1 (ADR-0005) — a two-handed guard simply never fires, which was
    verified against a real recording containing zero two-hand frames. A kill switch that cannot
    physically trigger is worse than a slightly loose one.
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        f = w.latest
        hands = [h for h in (f.left, f.right) if h is not None]
        if not hands:
            return 0.0
        if cfg.panic.require_both_hands and len(hands) < 2:  # tuning-exempt: both hands
            return 0.0
        openness = min(
            _ramp(h.openness, _lookup(cfg, open_key), above=True, upper=1.0) for h in hands
        )
        still = min(_ramp(h.palm_speed, _lookup(cfg, speed_key), above=False) for h in hands)
        return min(openness, still)

    return g


# --- combinators -----------------------------------------------------------------------


def all_of(*guards: Guard) -> Guard:
    def g(w, ctx, cfg):
        return min((x(w, ctx, cfg) for x in guards), default=0.0)

    return g


def any_of(*guards: Guard) -> Guard:
    def g(w, ctx, cfg):
        return max((x(w, ctx, cfg) for x in guards), default=0.0)

    return g


def never() -> Guard:
    def g(w, ctx, cfg):
        return 0.0

    return g


def always() -> Guard:
    def g(w, ctx, cfg):
        return 1.0

    return g


def for_all_frames(inner: Guard) -> Guard:
    """The weakest frame in the window wins.

    This is how the scope doc's "velocity crosses a hard threshold for the FULL window" becomes
    executable — and it is itself a hysteresis mechanism, because a single frame dipping below
    threshold defeats the whole window.
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        return min(
            (inner(FeatureWindow(frames=(f,)), ctx, cfg) for f in w.frames), default=0.0
        )

    return g


def for_enter_fraction(mode: ModeId, inner: Guard) -> Guard:
    """Like `for_fraction`, but reads `arbitration.enter_fraction[mode]`.

    Entering and sustaining tolerate different amounts of noise, so they get separate knobs.
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        scores = sorted(inner(FeatureWindow(frames=(f,)), ctx, cfg) for f in w.frames)
        if not scores:
            return 0.0
        fraction = cfg.arbitration.enter_fraction[mode]
        idx = min(len(scores) - 1, int(len(scores) * (1.0 - fraction)))
        return scores[idx]

    return g


def for_fraction(mode: ModeId, inner: Guard) -> Guard:
    """The score at `arbitration.sustain_fraction[mode]` across the window.

    A softer `for_all_frames`, used for *sustain* guards where one dropped tracking frame must not
    end the mode mid-gesture. The fraction is config, not a literal, so it is calibratable.
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        scores = sorted(inner(FeatureWindow(frames=(f,)), ctx, cfg) for f in w.frames)
        if not scores:
            return 0.0
        fraction = cfg.arbitration.sustain_fraction[mode]
        idx = min(len(scores) - 1, int(len(scores) * (1.0 - fraction)))
        return scores[idx]

    return g


def held_for(ms_key: str, inner: Guard) -> Guard:
    """True only once `inner` has held across at least `ms_key` ms OF WINDOW.

    Note this is bounded by the window span, so it cannot express a hold longer than the window.
    For mode ENTRY use `arbitration.hold_ms` instead, which the engine tracks across windows —
    expressing a 450ms macro dwell here with a 250ms window silently made macro unreachable.
    Kept for guards that genuinely mean "throughout the window".
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        if w.span_ms < _lookup(cfg, ms_key):
            return 0.0
        return for_all_frames(inner)(w, ctx, cfg)

    return g


def requires_cap(capability: str, inner: Guard) -> Guard:
    """Disable a mode when the backend that would execute it is absent.

    A mode that can be entered but whose intents can never be dispatched is strictly worse than
    one that is off: it takes the user out of the mode they wanted and does nothing.
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        return inner(w, ctx, cfg) if capability in ctx.capabilities else 0.0

    return g


def in_chord(*poses: str) -> Guard:
    """Gate a mode on the off-hand holding one of these poses.

    This is what makes the same physical gesture mean different things — the scope doc's Shift
    key. Modes declaring no chord are unaffected, so chording is purely additive.
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        from app.arbitration.chording import detect

        chord = detect(w, cfg)
        return 1.0 if chord.active and chord.pose in poses else 0.0

    return g


def no_chord() -> Guard:
    """The unmodified case. A mode that would otherwise fire while a modifier is held can declare
    this, the way an unmodified keypress differs from Shift+key."""

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        from app.arbitration.chording import detect

        return 0.0 if detect(w, cfg).active else 1.0

    return g


def in_app_class(*classes: str) -> Guard:
    """Gate on Jev point A's answer — WITHOUT importing the decision layer.

    The class arrives on `DecisionContext`, which is a frozen input to `step()`. That is the Jev
    firewall in practice: arbitration can read the last answer and can see how stale it is, but
    has no way to ask for a new one.
    """

    def g(w: FeatureWindow, ctx: DecisionContext, cfg: Config) -> float:
        return 1.0 if ctx.app_class.value in classes else 0.0

    return g


# --- config lookup ---------------------------------------------------------------------

_LOOKUP: dict[str, Callable[[Config], float]] = {
    "gross.speed": lambda c: c.gross.speed,
    "gross.speed_sustain": lambda c: c.gross.speed_sustain,
    "gross.coherence": lambda c: c.gross.coherence,
    "precision.max_palm_speed": lambda c: c.precision.max_palm_speed,
    "precision.max_palm_speed_sustain": lambda c: c.precision.max_palm_speed_sustain,
    "precision.index_extension": lambda c: c.precision.index_extension,
    "macro.max_speed": lambda c: c.macro.max_speed,
    "macro.max_openness": lambda c: c.macro.max_openness,
    "macro.template_cosine_min": lambda c: c.macro.template_cosine_min,
    "macro.dwell_ms": lambda c: c.macro.dwell_ms,
    "panic.both_open_min": lambda c: c.panic.both_open_min,
    "panic.max_speed": lambda c: c.panic.max_speed,
    "panic.hold_ms": lambda c: c.panic.hold_ms,
}


class UnknownThreshold(KeyError):
    pass


def _lookup(cfg: Config, key: str) -> float:
    try:
        return _LOOKUP[key](cfg)
    except KeyError as e:
        raise UnknownThreshold(
            f"guard referenced '{key}', which is not in guards._LOOKUP. Every threshold must come "
            f"from config/default.toml — add it there and register it here."
        ) from e
