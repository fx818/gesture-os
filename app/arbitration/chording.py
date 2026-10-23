"""Bimanual chording — the left hand as a modifier key.

The scope doc's insight: holding a pose with the off-hand changes what the acting hand's gestures
mean, exactly as Shift changes what a keyboard key does. The same small vocabulary of gestures
then covers a much larger command space without the user memorising more shapes.

Pure, like everything else in `arbitration/`. The chord is derived from the current feature window
and the user's own pose library — no I/O, no clock.

Two design points worth keeping:

  * The chord hand is whichever hand is NOT acting, not "the left hand". A left-handed user points
    with their left; hard-coding handedness would make the system unusable for them, and the scope
    doc's accessibility framing makes that unacceptable.
  * A chord must be a RECOGNISED pose, never merely "the other hand is visible". A hand resting in
    frame would otherwise silently change what every gesture means.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.types import FeatureWindow, Handedness, HandFeatures


@dataclass(frozen=True, slots=True)
class Chord:
    """The modifier currently held, if any."""

    pose: str
    hand: Handedness
    similarity: float

    @staticmethod
    def none() -> Chord:
        return Chord("", Handedness.LEFT, 0.0)

    @property
    def active(self) -> bool:
        return bool(self.pose)


def acting_hand(frame) -> tuple[HandFeatures | None, Handedness | None]:
    """The hand doing the work: the faster-moving one when both are present.

    Not "the right hand". With two hands tracked the acting hand is the one in motion, which is
    what makes this work for either handedness without a setting.
    """
    left, right = frame.left, frame.right
    if left is None and right is None:
        return None, None
    if left is None:
        return right, Handedness.RIGHT
    if right is None:
        return left, Handedness.LEFT
    if right.palm_speed >= left.palm_speed:
        return right, Handedness.RIGHT
    return left, Handedness.LEFT


def detect(window: FeatureWindow, cfg: Config) -> Chord:
    """The chord held by the non-acting hand, or `Chord.none()`."""
    if cfg.poses.is_empty:
        return Chord.none()

    frame = window.latest
    if frame.left is None or frame.right is None:
        return Chord.none()

    _, acting = acting_hand(frame)
    if acting is None:
        return Chord.none()

    modifier_hand = Handedness.LEFT if acting is Handedness.RIGHT else Handedness.RIGHT
    modifier = frame.left if modifier_hand is Handedness.LEFT else frame.right
    if modifier is None:
        return Chord.none()

    # The modifier must be HELD, not waved. A moving off-hand is gesturing or reaching, not
    # holding a modifier down.
    if modifier.palm_speed > cfg.macro.max_speed:
        return Chord.none()

    match = cfg.poses.best(modifier.joint_angles)
    if not match.matched or match.similarity < cfg.macro.template_cosine_min:
        return Chord.none()
    return Chord(pose=match.name, hand=modifier_hand, similarity=match.similarity)
