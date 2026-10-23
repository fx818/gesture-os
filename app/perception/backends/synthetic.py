"""Analytic landmark streams. No camera, no model, fully deterministic.

Two jobs:

  * let the arbitration engine be written and tested BEFORE any fixture is recorded, which
    decouples the engine phase from the recording phase if recording slips
  * generate the pathological cases a human cannot reliably perform on demand — a hand parked
    exactly on a threshold, a perfectly straight swipe at a chosen speed

Anatomically these hands are an approximation, and deliberately so: their job is to exercise
feature extraction and the state machine over known-correct kinematics, not to look real. Real
hands come from `fixtures/sessions/`, recorded in P2.

Every generator takes a seed. Same seed, same floats, forever — otherwise golden intent streams
stop reproducing.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Iterator, Sequence

from app.perception.source import SourceMeta
from app.types import Frame, Hand, Handedness, Landmark, Vec3

# Canonical neutral right hand, normalized, fingers pointing "up" (-y in image coordinates).
# Origin is the palm centroid; `synth_hand` translates and scales from here.
_CANONICAL: tuple[tuple[float, float], ...] = (
    (0.000, 0.100),   # WRIST
    (-0.050, 0.070),  # THUMB_CMC
    (-0.090, 0.030),  # THUMB_MCP
    (-0.120, 0.000),  # THUMB_IP
    (-0.140, -0.020),  # THUMB_TIP
    (-0.060, -0.010),  # INDEX_MCP
    (-0.070, -0.070),  # INDEX_PIP
    (-0.075, -0.110),  # INDEX_DIP
    (-0.080, -0.150),  # INDEX_TIP
    (-0.020, -0.020),  # MIDDLE_MCP
    (-0.020, -0.080),  # MIDDLE_PIP
    (-0.020, -0.130),  # MIDDLE_DIP
    (-0.020, -0.170),  # MIDDLE_TIP
    (0.020, -0.015),   # RING_MCP
    (0.020, -0.070),   # RING_PIP
    (0.020, -0.115),   # RING_DIP
    (0.020, -0.150),   # RING_TIP
    (0.060, 0.000),    # PINKY_MCP
    (0.065, -0.050),   # PINKY_PIP
    (0.068, -0.085),   # PINKY_DIP
    (0.070, -0.115),   # PINKY_TIP
)

# (mcp, pip, dip, tip) per finger, thumb first
_CHAINS: tuple[tuple[Landmark, ...], ...] = (
    (Landmark.THUMB_MCP, Landmark.THUMB_IP, Landmark.THUMB_TIP),
    (Landmark.INDEX_MCP, Landmark.INDEX_PIP, Landmark.INDEX_DIP, Landmark.INDEX_TIP),
    (Landmark.MIDDLE_MCP, Landmark.MIDDLE_PIP, Landmark.MIDDLE_DIP, Landmark.MIDDLE_TIP),
    (Landmark.RING_MCP, Landmark.RING_PIP, Landmark.RING_DIP, Landmark.RING_TIP),
    (Landmark.PINKY_MCP, Landmark.PINKY_PIP, Landmark.PINKY_DIP, Landmark.PINKY_TIP),
)

DEFAULT_FPS = 30.0


def synth_hand(
    cx: float,
    cy: float,
    *,
    scale: float = 1.0,
    openness: float = 1.0,
    index_extension: float | None = None,
    pinch: float = 1.0,
    handedness: Handedness = Handedness.RIGHT,
    jitter: float = 0.0,
    rng: random.Random | None = None,
    tracking_score: float = 0.97,
) -> Hand:
    """Build one hand.

    openness         1.0 flat, 0.0 fist (fingers collapse toward their MCP)
    index_extension  overrides openness for the index finger only — the pointing pose
    pinch            1.0 natural thumb/index separation, 0.0 tips touching
    jitter           gaussian noise in normalized units; use for tremor and for proving that
                     hysteresis survives a noisy signal
    """
    pts: list[list[float]] = [[x, y] for x, y in _CANONICAL]

    for chain in _CHAINS:
        curl = openness
        if index_extension is not None and chain[0] is Landmark.INDEX_MCP:
            curl = index_extension
        anchor = pts[int(chain[0])]
        for lm in chain[1:]:
            i = int(lm)
            pts[i] = [
                anchor[0] + (pts[i][0] - anchor[0]) * curl,
                anchor[1] + (pts[i][1] - anchor[1]) * curl,
            ]

    if pinch < 1.0:
        ti, ii = int(Landmark.THUMB_TIP), int(Landmark.INDEX_TIP)
        tx, ty = pts[ti]
        ix, iy = pts[ii]
        pts[ti] = [ix + (tx - ix) * pinch, iy + (ty - iy) * pinch]

    if handedness is Handedness.LEFT:
        pts = [[-x, y] for x, y in pts]

    r = rng or random.Random(0)
    out: list[Vec3] = []
    for x, y in pts:
        nx = cx + x * scale
        ny = cy + y * scale
        if jitter:
            nx += r.gauss(0.0, jitter)
            ny += r.gauss(0.0, jitter)
        out.append((nx, ny, 0.0))

    return Hand(handedness=handedness, tracking_score=tracking_score, landmarks=tuple(out))


class SyntheticLandmarkSource:
    """Wraps a per-frame callable into a LandmarkSource.

    `build(i, t_ms, rng) -> tuple[Hand, ...]` — returning an empty tuple means "no hand in frame",
    which is a signal the arbiter acts on, not an error.
    """

    def __init__(
        self,
        name: str,
        build: Callable[[int, float, random.Random], Sequence[Hand]],
        *,
        duration_s: float,
        fps: float = DEFAULT_FPS,
        width: int = 640,
        height: int = 480,
        seed: int = 0,
    ) -> None:
        self._build = build
        self._duration_s = duration_s
        self._fps = fps
        self._seed = seed
        self.meta = SourceMeta(
            name=name, fps_nominal=fps, width=width, height=height, model="synthetic",
            notes=f"seed={seed}",
        )

    def frames(self) -> Iterator[Frame]:
        rng = random.Random(self._seed)
        n = max(1, int(round(self._duration_s * self._fps)))
        for i in range(n):
            t_ms = i * 1000.0 / self._fps
            hands = tuple(self._build(i, t_ms, rng))
            yield Frame(
                seq=i, t_ms=t_ms, width=self.meta.width, height=self.meta.height, hands=hands
            )

    def close(self) -> None:
        return None


# --------------------------------------------------------------------------------------
# Generators. Speeds are in palm widths per second, matching config/default.toml.
# --------------------------------------------------------------------------------------

_PALM_WIDTH = abs(_CANONICAL[int(Landmark.PINKY_MCP)][0] - _CANONICAL[int(Landmark.INDEX_MCP)][0])


def absent(duration_s: float = 1.0, **kw) -> SyntheticLandmarkSource:
    """No hand in frame at all."""
    return SyntheticLandmarkSource("absent", lambda i, t, r: (), duration_s=duration_s, **kw)


def rest(duration_s: float = 2.0, *, jitter: float = 0.0008, **kw) -> SyntheticLandmarkSource:
    """A relaxed hand sitting near the desk. The single most important negative case: this must
    produce zero mode transitions for its whole duration."""

    def build(i, t, r):
        return (synth_hand(0.5, 0.6, openness=0.45, jitter=jitter, rng=r),)

    return SyntheticLandmarkSource("rest", build, duration_s=duration_s, **kw)


def linear_swipe(
    direction: str = "left",
    *,
    speed: float = 2.4,
    duration_s: float = 0.4,
    openness: float = 0.9,
    **kw,
) -> SyntheticLandmarkSource:
    """A committed sweep: constant high velocity, perfectly coherent heading.

    `speed` is palm widths/second, so it compares directly against config `gross.speed`.
    """
    # Image coordinates: y grows DOWNWARD, so a hand moving physically up has a NEGATIVE dy.
    # The camera mirror is horizontal only (cv2.flip axis 1), so it does not touch this.
    axis, sign = {
        "left": ("x", -1.0), "right": ("x", 1.0),
        "up": ("y", -1.0), "down": ("y", 1.0),
    }.get(direction, ("x", -1.0))
    per_frame = sign * speed * _PALM_WIDTH / kw.get("fps", DEFAULT_FPS)
    start = 0.75 if sign < 0 else 0.25

    def build(i, t, r):
        moved = start + per_frame * i
        x, y = (moved, 0.5) if axis == "x" else (0.5, moved)
        return (synth_hand(x, y, openness=openness, rng=r),)

    return SyntheticLandmarkSource(f"swipe_{direction}", build, duration_s=duration_s, **kw)


def swipe_left(**kw) -> SyntheticLandmarkSource:
    return linear_swipe("left", **kw)


def swipe_right(**kw) -> SyntheticLandmarkSource:
    return linear_swipe("right", **kw)


def swipe_up(**kw) -> SyntheticLandmarkSource:
    return linear_swipe("up", **kw)


def swipe_down(**kw) -> SyntheticLandmarkSource:
    return linear_swipe("down", **kw)


def precision_trace(
    duration_s: float = 2.0, *, speed: float = 0.35, jitter: float = 0.0006, **kw
) -> SyntheticLandmarkSource:
    """Index extended, others curled, tracing a slow circle. The cursor case.

    `speed` is palm-widths per second, the same unit as `config/default.toml`, so a generator and
    a threshold can be compared directly instead of through a radius-and-frequency conversion.
    """
    fps = kw.get("fps", DEFAULT_FPS)
    radius = 0.08
    # linear speed v = 2*pi*r*f  ->  f = v*palm_width / (2*pi*r)
    freq = speed * _PALM_WIDTH / (2 * math.pi * radius)

    def build(i, t, r):
        a = 2 * math.pi * (i / fps) * freq
        return (
            synth_hand(
                0.5 + radius * math.cos(a),
                0.5 + radius * math.sin(a),
                openness=0.15,
                index_extension=1.0,
                jitter=jitter,
                rng=r,
            ),
        )

    return SyntheticLandmarkSource("precision_trace", build, duration_s=duration_s, **kw)


def pinch_click(
    duration_s: float = 1.2, *, at_s: float = 0.6, hold_s: float = 0.15, **kw
) -> SyntheticLandmarkSource:
    """Precision pose with one discrete pinch. Should produce exactly one down/up pair."""

    def build(i, t, r):
        pinching = at_s * 1000 <= t < (at_s + hold_s) * 1000
        return (
            synth_hand(
                0.5, 0.5, openness=0.15, index_extension=1.0,
                pinch=0.1 if pinching else 1.0, jitter=0.0005, rng=r,
            ),
        )

    return SyntheticLandmarkSource("pinch_click", build, duration_s=duration_s, **kw)


def pose_hold(
    duration_s: float = 1.0, *, openness: float = 0.0, **kw
) -> SyntheticLandmarkSource:
    """A still, held pose — the macro dwell case."""

    def build(i, t, r):
        return (synth_hand(0.5, 0.5, openness=openness, jitter=0.0004, rng=r),)

    return SyntheticLandmarkSource("pose_hold", build, duration_s=duration_s, **kw)


def hover_at_threshold(
    duration_s: float = 3.0, *, speed: float = 1.8, noise: float = 0.05, reverse_s: float = 0.6, **kw
) -> SyntheticLandmarkSource:
    """Hold velocity exactly ON a threshold, with a few percent of noise, reversing periodically.

    The hysteresis torture test. A single-threshold design oscillates in and out of GROSS dozens of
    times here; the Schmitt + streak + dwell + refractory stack must produce at most one transition.

    Constant speed with periodic reversal, not a sinusoid: a sinusoid spends most of its time away
    from the threshold, which is the opposite of what this fixture is for. (The first version of
    this generator made exactly that mistake and measured 0.15 pw/s instead of 1.8.)
    """
    fps = kw.get("fps", DEFAULT_FPS)
    step = speed * _PALM_WIDTH / fps
    flip_every = max(1, int(reverse_s * fps))

    def build(i, t, r):
        leg = i // flip_every
        within = i % flip_every
        direction = 1.0 if leg % 2 == 0 else -1.0
        base = 0.5 - direction * (flip_every * step) / 2
        jitter_step = step * (1.0 + r.gauss(0.0, noise))
        return (synth_hand(base + direction * within * jitter_step, 0.5, openness=0.8, rng=r),)

    return SyntheticLandmarkSource("hover_at_threshold", build, duration_s=duration_s, **kw)


def two_hand_panic(duration_s: float = 1.0, **kw) -> SyntheticLandmarkSource:
    """Both palms open and still — the kill switch."""

    def build(i, t, r):
        return (
            synth_hand(0.35, 0.5, openness=1.0, jitter=0.0003, rng=r, handedness=Handedness.LEFT),
            synth_hand(0.65, 0.5, openness=1.0, jitter=0.0003, rng=r, handedness=Handedness.RIGHT),
        )

    return SyntheticLandmarkSource("two_hand_panic", build, duration_s=duration_s, **kw)


def tremor(duration_s: float = 2.0, *, amplitude: float = 0.004, **kw) -> SyntheticLandmarkSource:
    """High-amplitude tremor at a resting pose. The accessibility case: per-user calibration has
    to absorb this without it reading as intentional motion."""

    def build(i, t, r):
        return (
            synth_hand(0.5, 0.5, openness=0.2, index_extension=1.0, jitter=amplitude, rng=r),
        )

    return SyntheticLandmarkSource("tremor", build, duration_s=duration_s, **kw)


GENERATORS: dict[str, Callable[..., SyntheticLandmarkSource]] = {
    "absent": absent,
    "rest": rest,
    "swipe_left": swipe_left,
    "swipe_right": swipe_right,
    "swipe_up": swipe_up,
    "swipe_down": swipe_down,
    "precision_trace": precision_trace,
    "pinch_click": pinch_click,
    "pose_hold": pose_hold,
    "hover_at_threshold": hover_at_threshold,
    "two_hand_panic": two_hand_panic,
    "tremor": tremor,
}
