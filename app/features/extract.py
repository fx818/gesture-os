"""Landmarks -> features. Pure, and the only place raw geometry is interpreted.

Two invariants the rest of the system leans on:

  * **Everything is scaled by palm width** (index MCP to pinky MCP). A hand 30cm from the camera
    and the same hand 60cm away produce the same features, so one fixture validates both, and
    thresholds in config are in palm-widths-per-second rather than in pixels of a particular
    webcam at a particular distance.
  * **Time is data.** `extract` takes `t_ms` from the frame and never reads a clock. Replay is
    therefore bit-reproducible.

`extract` is a fold: `(state, frame, cfg) -> (state, FeatureFrame)`. The state holds only filter
history and the previous position — everything else is computed from the frame alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from app.config import PrecisionConfig
from app.features.filters import OneEuroVec2State, one_euro_step_vec2
from app.types import (
    BimanualFeatures,
    FeatureFrame,
    Frame,
    Hand,
    HandFeatures,
    Handedness,
    Landmark,
    Vec3,
)

# Three flexion angles per finger (MCP, PIP, DIP), five fingers.
_FINGER_CHAINS: tuple[tuple[Landmark, ...], ...] = (
    (Landmark.WRIST, Landmark.THUMB_CMC, Landmark.THUMB_MCP, Landmark.THUMB_IP, Landmark.THUMB_TIP),
    (Landmark.WRIST, Landmark.INDEX_MCP, Landmark.INDEX_PIP, Landmark.INDEX_DIP, Landmark.INDEX_TIP),
    (Landmark.WRIST, Landmark.MIDDLE_MCP, Landmark.MIDDLE_PIP, Landmark.MIDDLE_DIP, Landmark.MIDDLE_TIP),
    (Landmark.WRIST, Landmark.RING_MCP, Landmark.RING_PIP, Landmark.RING_DIP, Landmark.RING_TIP),
    (Landmark.WRIST, Landmark.PINKY_MCP, Landmark.PINKY_PIP, Landmark.PINKY_DIP, Landmark.PINKY_TIP),
)
_PALM = (
    Landmark.WRIST,
    Landmark.INDEX_MCP,
    Landmark.MIDDLE_MCP,
    Landmark.RING_MCP,
    Landmark.PINKY_MCP,
)
_FINGERTIPS = (
    Landmark.THUMB_TIP,
    Landmark.INDEX_TIP,
    Landmark.MIDDLE_TIP,
    Landmark.RING_TIP,
    Landmark.PINKY_TIP,
)

# A hand smaller than this in normalized units is a tracking artefact, not a hand. Dividing by it
# would produce enormous spurious velocities.
_MIN_PALM_WIDTH = 1e-4  # tuning-exempt: degenerate-geometry guard, not a tunable threshold

# Frames of heading history used for direction coherence. Short on purpose: coherence over the
# full window is computed by guards; this is the per-frame smoothed view.
_HEADING_HISTORY = 5  # tuning-exempt: buffer length, not a threshold


def _dist(a: Vec3, b: Vec3) -> float:
    return math.dist(a[:2], b[:2])


def _centroid(hand: Hand, points) -> Vec3:
    xs = [hand.at(p) for p in points]
    n = len(xs)
    return (sum(p[0] for p in xs) / n, sum(p[1] for p in xs) / n, sum(p[2] for p in xs) / n)


def _angle(a: Vec3, b: Vec3, c: Vec3) -> float:
    """Interior angle at b, in radians. Translation and scale invariant by construction."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.acos(cos)


@dataclass(frozen=True, slots=True)
class HandState:
    filter_state: OneEuroVec2State = OneEuroVec2State()
    prev_centroid: tuple[float, float] | None = None   # filtered; drives the cursor
    prev_raw: tuple[float, float] | None = None        # unfiltered; drives velocity
    prev_t_ms: float | None = None
    headings: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractState:
    hands: dict[Handedness, HandState] = field(default_factory=dict)

    def for_hand(self, h: Handedness) -> HandState:
        return self.hands.get(h, HandState())


def _hand_features(
    hand: Hand, t_ms: float, state: HandState, cfg: PrecisionConfig
) -> tuple[HandState, HandFeatures]:
    palm_width = max(_dist(hand.at(Landmark.INDEX_MCP), hand.at(Landmark.PINKY_MCP)), _MIN_PALM_WIDTH)
    raw_centroid = _centroid(hand, _PALM)

    filter_state, (cx, cy) = one_euro_step_vec2(
        state.filter_state, raw_centroid[0], raw_centroid[1], t_ms, cfg.one_euro
    )

    # Velocity comes from the RAW centroid, not the filtered one.
    #
    # One Euro exists to smooth the CURSOR, not to attenuate the EVIDENCE. Deriving velocity from
    # the filtered position made a 2.4 palm-width/s swipe measure 1.63 — the filter is still
    # settling over a 400ms gesture — which pushed a committed sweep under the gross threshold and
    # left it indistinguishable from slow pointing. The filtered centroid is still what the
    # cursor follows; arbitration reads the truth.
    velocity = (0.0, 0.0)
    speed = 0.0
    if state.prev_raw is not None and state.prev_t_ms is not None:
        dt_s = (t_ms - state.prev_t_ms) / 1000.0
        if dt_s > 0.0:
            vx = (raw_centroid[0] - state.prev_raw[0]) / dt_s / palm_width
            vy = (raw_centroid[1] - state.prev_raw[1]) / dt_s / palm_width
            velocity = (vx, vy)
            speed = math.hypot(vx, vy)

    heading = (0.0, 0.0)
    if speed > 0.0:
        heading = (velocity[0] / speed, velocity[1] / speed)
    headings = (state.headings + (heading,))[-_HEADING_HISTORY:]

    # Coherence: the length of the mean unit heading. 1.0 is a perfectly straight path; a hand
    # jittering in place averages to ~0. This is what separates a committed sweep from fidgeting.
    if headings:
        mx = sum(h[0] for h in headings) / len(headings)
        my = sum(h[1] for h in headings) / len(headings)
        coherence = math.hypot(mx, my)
    else:
        coherence = 0.0

    tip_spread = sum(_dist(hand.at(t), raw_centroid) for t in _FINGERTIPS) / len(_FINGERTIPS)
    openness = min(1.0, tip_spread / palm_width)

    angles: list[float] = []
    for chain in _FINGER_CHAINS:
        for i in range(len(chain) - 2):
            angles.append(_angle(hand.at(chain[i]), hand.at(chain[i + 1]), hand.at(chain[i + 2])))

    index_len = _dist(hand.at(Landmark.INDEX_TIP), hand.at(Landmark.INDEX_MCP)) / palm_width
    others = [
        _dist(hand.at(tip), hand.at(mcp)) / palm_width
        for tip, mcp in (
            (Landmark.MIDDLE_TIP, Landmark.MIDDLE_MCP),
            (Landmark.RING_TIP, Landmark.RING_MCP),
            (Landmark.PINKY_TIP, Landmark.PINKY_MCP),
        )
    ]
    # Pointing is the index being extended *relative to the others* — an open flat hand has a long
    # index too, and must not read as pointing.
    index_extension = max(0.0, min(1.0, index_len - (sum(others) / len(others))))

    fingertip_speeds = tuple(
        _dist(hand.at(tip), raw_centroid) / palm_width for tip in _FINGERTIPS
    )

    features = HandFeatures(
        palm_centroid=(cx, cy, raw_centroid[2]),
        palm_velocity=(velocity[0], velocity[1], 0.0),
        palm_speed=speed,
        palm_dir_coherence=coherence,
        fingertip_speeds=fingertip_speeds,
        openness=openness,
        joint_angles=tuple(angles),
        palm_normal=(0.0, 0.0, 1.0),
        wrist_roll=_angle(
            hand.at(Landmark.INDEX_MCP), hand.at(Landmark.WRIST), hand.at(Landmark.PINKY_MCP)
        ),
        pinch_thumb_index=_dist(hand.at(Landmark.THUMB_TIP), hand.at(Landmark.INDEX_TIP)) / palm_width,
        pinch_thumb_middle=_dist(hand.at(Landmark.THUMB_TIP), hand.at(Landmark.MIDDLE_TIP)) / palm_width,
        index_extension=index_extension,
        tracking_score=hand.tracking_score,
    )
    new_state = HandState(
        filter_state=filter_state,
        prev_centroid=(cx, cy),
        prev_raw=(raw_centroid[0], raw_centroid[1]),
        prev_t_ms=t_ms,
        headings=headings,
    )
    return new_state, features


def _bimanual(left: HandFeatures | None, right: HandFeatures | None) -> BimanualFeatures | None:
    if left is None or right is None:
        return None
    distance = math.dist(left.palm_centroid[:2], right.palm_centroid[:2])
    symmetry = 1.0 - min(1.0, abs(left.openness - right.openness))
    approach = -(left.palm_velocity[0] - right.palm_velocity[0])
    return BimanualFeatures(
        distance=distance,
        symmetry=symmetry,
        approach_rate=approach,
        both_open=min(left.openness, right.openness),
    )


def extract(
    state: ExtractState, frame: Frame, cfg: PrecisionConfig
) -> tuple[ExtractState, FeatureFrame]:
    """Pure. Same (state, frame, cfg) always yields the same (state, FeatureFrame)."""
    hands: dict[Handedness, HandState] = dict(state.hands)
    out: dict[Handedness, HandFeatures] = {}

    for hand in frame.hands:
        new_state, features = _hand_features(
            hand, frame.t_ms, state.for_hand(hand.handedness), cfg
        )
        hands[hand.handedness] = new_state
        out[hand.handedness] = features

    # A hand that left the frame must not keep its stale filter history: when it returns, the gap
    # would produce one enormous velocity spike that reads as a swipe.
    present = {h.handedness for h in frame.hands}
    for handedness in list(hands):
        if handedness not in present:
            hands.pop(handedness)

    left = out.get(Handedness.LEFT)
    right = out.get(Handedness.RIGHT)
    return (
        ExtractState(hands=hands),
        FeatureFrame(t_ms=frame.t_ms, right=right, left=left, bimanual=_bimanual(left, right)),
    )
