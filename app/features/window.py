"""Rolling feature window.

`push` returns an immutable `FeatureWindow` snapshot each frame. Guards are pure functions of one
of those, which is what lets the whole state machine be driven frame-by-frame from a file.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.types import FeatureFrame, FeatureWindow


@dataclass(frozen=True, slots=True)
class WindowBuffer:
    frames: tuple[FeatureFrame, ...] = ()
    span_ms: float = 250.0
    min_frames: int = 5

    def push(self, frame: FeatureFrame) -> tuple[WindowBuffer, FeatureWindow | None]:
        """Returns (buffer, window). The window is None until enough frames have accumulated —
        velocity needs two samples and coherence needs several, so acting on a partial window
        would fire on the first frame after the hand appears."""
        frames = self.frames + (frame,)
        # Trim by TIME, not by count. At a variable frame rate a fixed count would mean a window
        # that silently covers 250ms sometimes and 800ms other times, and every threshold
        # expressed in "per second" would drift with it.
        cutoff = frame.t_ms - self.span_ms
        frames = tuple(f for f in frames if f.t_ms >= cutoff)
        buf = WindowBuffer(frames=frames, span_ms=self.span_ms, min_frames=self.min_frames)
        if len(frames) < self.min_frames:
            return buf, None
        return buf, FeatureWindow(frames=frames)
