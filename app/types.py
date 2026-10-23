"""Cross-layer vocabulary.

This module imports nothing of ours and nothing third-party. Every value that crosses a layer
boundary is defined here, frozen, and hashable where it can be.

Two invariants that the rest of the system depends on:

1. Landmarks are stored NORMALIZED (x, y in 0..1 of the frame; z relative to the wrist), never in
   pixels. One fixture then validates a 720p laptop camera and a 1080p external one alike.
2. Time is carried as data on `Frame.t_ms`. Nothing downstream of perception may read a clock.
   That is what makes replay bit-reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Final

Vec3 = tuple[float, float, float]

LANDMARK_COUNT: Final = 21


class Landmark(IntEnum):
    """MediaPipe Hands landmark indices, named so feature code reads as anatomy."""

    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


FINGERTIPS: Final[tuple[Landmark, ...]] = (
    Landmark.THUMB_TIP,
    Landmark.INDEX_TIP,
    Landmark.MIDDLE_TIP,
    Landmark.RING_TIP,
    Landmark.PINKY_TIP,
)


class Handedness(StrEnum):
    LEFT = "left"
    RIGHT = "right"


class Capability(StrEnum):
    """What an effector backend can actually do on this machine.

    Backends declare these; the router checks them and degrades a feature visibly rather than
    raising. This is how the GNOME Shell extension stays an upgrade instead of a dependency:
    `ShortcutWindowManager` declares WINDOW_MOVE but not WINDOW_TILE_ARBITRARY.
    """

    POINTER_REL = "pointer.rel"
    SCROLL = "scroll"
    KEY_SYNTH = "key.synth"
    FOCUS_READ = "focus.read"
    UI_TREE_READ = "ui.tree.read"
    UI_ACTION_RECORD = "ui.action.record"
    SYSTEM_SUSPEND = "system.suspend"
    WINDOW_MOVE = "window.move"
    WINDOW_TILE_ARBITRARY = "window.tile.arbitrary"
    WINDOW_LIST = "window.list"
    OVERLAY = "overlay"


class ModeId(StrEnum):
    """The arbitration engine's states. Mirrors the state diagram in docs/scope.md."""

    IDLE = "idle"
    PRECISION = "precision"
    MACRO = "macro"
    GROSS = "gross"
    SLIDER = "slider"
    PANIC = "panic"


# --------------------------------------------------------------------------------------
# Perception
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hand:
    handedness: Handedness
    tracking_score: float
    landmarks: tuple[Vec3, ...]  # exactly LANDMARK_COUNT, normalized

    def __post_init__(self) -> None:
        if len(self.landmarks) != LANDMARK_COUNT:
            raise ValueError(
                f"expected {LANDMARK_COUNT} landmarks, got {len(self.landmarks)}"
            )

    def at(self, lm: Landmark) -> Vec3:
        return self.landmarks[int(lm)]


@dataclass(frozen=True, slots=True)
class Frame:
    """One perception tick. `hands` may be empty — absence is a signal, not an error."""

    seq: int
    t_ms: float  # monotonic ms since source start — THE ONLY CLOCK
    width: int
    height: int
    hands: tuple[Hand, ...]  # 0, 1 or 2

    def hand(self, which: Handedness) -> Hand | None:
        for h in self.hands:
            if h.handedness is which:
                return h
        return None


# --------------------------------------------------------------------------------------
# Features  (all scale- and translation-invariant: distances are in palm widths)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HandFeatures:
    palm_centroid: Vec3
    palm_velocity: Vec3  # palm-widths per second
    palm_speed: float
    palm_dir_coherence: float  # 0..1; 1.0 means perfectly straight over the window
    fingertip_speeds: tuple[float, ...]  # 5, relative to the palm
    openness: float  # 0 fist .. 1 flat
    joint_angles: tuple[float, ...]  # 15 flexion angles, radians
    palm_normal: Vec3
    wrist_roll: float
    pinch_thumb_index: float  # palm widths
    pinch_thumb_middle: float
    index_extension: float  # 0..1, soft — never thresholded into a bool in features/
    tracking_score: float


@dataclass(frozen=True, slots=True)
class BimanualFeatures:
    distance: float
    symmetry: float
    approach_rate: float
    both_open: float


@dataclass(frozen=True, slots=True)
class FeatureFrame:
    t_ms: float
    right: HandFeatures | None
    left: HandFeatures | None
    bimanual: BimanualFeatures | None

    @property
    def present(self) -> bool:
        return self.right is not None or self.left is not None


@dataclass(frozen=True, slots=True)
class FeatureWindow:
    """A rolling ~250ms view. Immutable snapshot; guards are pure functions of one of these."""

    frames: tuple[FeatureFrame, ...]  # oldest -> newest

    def __post_init__(self) -> None:
        if not self.frames:
            raise ValueError("FeatureWindow may not be empty")

    @property
    def latest(self) -> FeatureFrame:
        return self.frames[-1]

    @property
    def t_end(self) -> float:
        return self.frames[-1].t_ms

    @property
    def span_ms(self) -> float:
        return self.frames[-1].t_ms - self.frames[0].t_ms

    def __len__(self) -> int:
        return len(self.frames)


# --------------------------------------------------------------------------------------
# Desktop context  (produced by effectors, consumed by arbitration as frozen input)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FocusInfo:
    app_name: str
    window_title: str
    role: str
    pid: int | None
    t_ms: float


class AppClass(StrEnum):
    """Closed set for Jev point A. `UNKNOWN` is a real answer, not an error."""

    CODE_EDITOR = "code_editor"
    BROWSER = "browser"
    TERMINAL = "terminal"
    PRESENTATION = "presentation"
    MEDIA_PLAYER = "media_player"
    FILE_MANAGER = "file_manager"
    DOCUMENT_EDITOR = "document_editor"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------------------
# Windows and overlay  (effector vocabulary; lives here so decision/ and routing/ can name
# these without importing effectors/)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    index: int
    rect: Rect
    primary: bool


@dataclass(frozen=True, slots=True)
class WindowInfo:
    wid: str
    app_name: str
    title: str
    rect: Rect
    monitor: int
    workspace: int
    focused: bool


@dataclass(frozen=True, slots=True)
class LayoutSnapshot:
    monitors: tuple[MonitorInfo, ...]
    windows: tuple[WindowInfo, ...]
    t_ms: float

    def focused(self) -> WindowInfo | None:
        for w in self.windows:
            if w.focused:
                return w
        return None


@dataclass(frozen=True, slots=True)
class UiAction:
    """One recorded step from the UI-automation layer. Text-shaped on purpose: this is exactly
    what Jev point D reads when deciding whether a step was incidental."""

    t_ms: float
    verb: str  # "click" | "focus" | "type" | "launch" | ...
    target_role: str
    target_name: str
    app_name: str


@dataclass(frozen=True, slots=True)
class Wedge:
    action_id: str
    label: str
    score: float


@dataclass(frozen=True, slots=True)
class HudState:
    mode: ModeId
    mode_confidence: float
    app_class: str
    dwell_progress: float  # 0..1 during the macro dwell; the abort window
    dwell_preview: str | None
    degraded: tuple[str, ...]  # capabilities missing, surfaced to the user
    # Without these the HUD cannot distinguish "no hand in frame" from "hand present but idle" —
    # the one question you need answered while gesturing at it. That ambiguity blocked live
    # diagnosis twice before it was added.
    hands: int = 0
    palm_speed: float = 0.0


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """The outside world as a frozen snapshot, passed INTO the pure engine.

    `step()` reads this. It cannot refresh it, await it, or request a judgment — that is the Jev
    firewall (ADR-0001). `app_class_age_ms` exists so guards can distrust a stale answer.
    """

    focus: FocusInfo | None
    app_class: AppClass
    app_class_confidence: float
    app_class_age_ms: float
    active_chord: str | None
    recent_actions: tuple[str, ...]
    capabilities: frozenset[Capability]

    @staticmethod
    def empty() -> DecisionContext:
        return DecisionContext(
            focus=None,
            app_class=AppClass.UNKNOWN,
            app_class_confidence=0.0,
            app_class_age_ms=float("inf"),
            active_chord=None,
            recent_actions=(),
            capabilities=frozenset(),
        )
