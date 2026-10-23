"""Perception port.

`LandmarkSource` is the seam that makes the camera optional. A recorded NDJSON file, a synthetic
generator and a live MediaPipe camera are interchangeable behind it, so the entire stack downstream
develops and tests without hardware.

Only `perception/backends/mediapipe_camera.py` may import mediapipe or cv2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Protocol, runtime_checkable

from app.types import Frame


@dataclass(frozen=True, slots=True)
class SourceMeta:
    """Travels with a stream and is written into the fixture sidecar. `model` and `git_sha` are
    what let you tell, months later, why an old fixture stopped reproducing."""

    name: str
    fps_nominal: float
    width: int
    height: int
    model: str = "synthetic"
    git_sha: str = ""
    recorded: str = ""
    notes: str = ""
    segments: tuple[dict, ...] = field(default_factory=tuple)


@runtime_checkable
class LandmarkSource(Protocol):
    meta: SourceMeta

    def frames(self) -> Iterator[Frame]: ...
    def close(self) -> None: ...


class TeeSource:
    """Passes frames through while writing them to a sink. This is `record`.

    Recording is therefore never a separate code path from running — you record by wrapping
    whatever source you were already using, so a fixture is by construction what the system saw.
    """

    def __init__(self, inner: LandmarkSource, writer) -> None:
        self.inner = inner
        self.writer = writer
        self.meta = inner.meta

    def frames(self) -> Iterator[Frame]:
        for frame in self.inner.frames():
            self.writer.write(frame)
            yield frame

    def close(self) -> None:
        try:
            self.writer.close()
        finally:
            self.inner.close()
