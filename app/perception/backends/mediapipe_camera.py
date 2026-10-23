"""The only module permitted to import mediapipe or cv2 (enforced by .importlinter).

Everything downstream sees `Frame` objects from `app.types`, which is what lets the entire engine
develop and test against recorded and synthetic sources with no camera present.

Latency notes, because this is where the 50 ms budget is won or lost:
  * `CAP_PROP_BUFFERSIZE=1` — without it V4L2 queues frames and you consume stale ones, adding a
    whole frame interval of lag that looks like model slowness.
  * MJPG over YUYV — at 640x480 the uncompressed format often caps at 10 fps on laptop cameras.
  * The "lite" float16 model. `model_complexity` in config maps onto which .task file is used.
  * Timestamps are captured BEFORE inference, so `Frame.t_ms` measures when light hit the sensor,
    not when the model finished. Anything else silently hides inference cost from `bench`.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Iterator

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

from dataclasses import dataclass, field

from app.config import PerceptionConfig
from app.perception.source import SourceMeta
from app.types import Frame, Hand, Handedness


@dataclass
class StageTimings:
    """Per-stage wall time, so `bench` can say WHICH stage is over budget rather than reporting
    one opaque number. Without this every latency question becomes an afternoon of guesswork."""

    capture: list[float] = field(default_factory=list)
    convert: list[float] = field(default_factory=list)
    inference: list[float] = field(default_factory=list)
    assemble: list[float] = field(default_factory=list)

    def reset(self) -> None:
        for v in (self.capture, self.convert, self.inference, self.assemble):
            v.clear()


class _LatestFrameGrabber:
    """Capture on its own thread, keeping only the newest frame.

    Without this, `cap.read()` and inference run in series: the loop blocks ~23 ms waiting for the
    sensor, then spends ~40 ms inferring, during which the camera produces frames that are thrown
    away anyway. Measured 64 ms per iteration for 40 ms of actual work.

    Overlapping them means the pipeline runs at the inference rate and always infers on the most
    recent frame. Deliberately a single slot, not a queue: a backlog of stale frames is worse than
    dropping them, because a cursor driven from a queued frame lags by the whole backlog.
    """

    def __init__(self, cap) -> None:
        self._cap = cap
        self._lock = threading.Lock()
        self._frame = None
        self._stamp = 0.0
        self._seq = 0
        self._running = True
        self._new = threading.Event()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                continue
            with self._lock:
                self._frame = frame
                self._stamp = time.monotonic()
                self._seq += 1
            self._new.set()

    def latest(self, timeout: float = 1.0):
        """Block until a frame NEWER than the last one returned is available.

        Returning the same frame twice would make the feature layer see zero velocity for a frame
        it already processed, which reads as a hand that briefly stopped moving.
        """
        deadline = time.monotonic() + timeout
        last_seq = getattr(self, "_last_returned", -1)
        while time.monotonic() < deadline:
            with self._lock:
                if self._seq != last_seq and self._frame is not None:
                    self._last_returned = self._seq
                    # COPY under the lock. Returning the array by reference was a data race:
                    # OpenCV reuses its capture buffer across read() calls, so the capture thread
                    # would overwrite the very array inference was running on. The result was torn
                    # frames and roughly HALF the hand detections — 17/56 through the grabber
                    # against 27/40 reading the camera directly. It looked like a lighting or
                    # model problem for a long time.
                    #
                    # A 640x480x3 copy is under a millisecond, against ~34ms of inference.
                    return self._frame.copy(), self._stamp
            self._new.wait(0.005)
            self._new.clear()
        return None, 0.0

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = REPO_ROOT / "models" / "hand_landmarker.task"


class ModelMissing(RuntimeError):
    pass


def _handedness(label: str) -> Handedness:
    # MediaPipe reports handedness from the camera's point of view on a mirrored image. The scope
    # doc's bimanual chording cares which of the USER's hands it is, and `Left`/`Right` as reported
    # already refer to the user when the frame is mirrored, which is what `mirror=True` does below.
    return Handedness.LEFT if label.lower().startswith("l") else Handedness.RIGHT


class MediaPipeCameraSource:
    def __init__(
        self,
        cfg: PerceptionConfig,
        *,
        device: int | str = 0,
        model_path: Path = DEFAULT_MODEL,
        mirror: bool = True,
        max_frames: int | None = None,
        max_seconds: float | None = None,
    ) -> None:
        if not Path(model_path).exists():
            raise ModelMissing(f"{model_path} missing — run `make model`")

        self.cfg = cfg
        self.mirror = mirror
        self.max_frames = max_frames
        self.max_seconds = max_seconds

        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            raise RuntimeError(f"could not open camera {device!r}")
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
        self._cap.set(cv2.CAP_PROP_FPS, cfg.fps)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if cfg.exposure > 0:
            # CAP_PROP_AUTO_EXPOSURE = 1 selects MANUAL mode in the V4L2 backend (3 is auto).
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
            self._cap.set(cv2.CAP_PROP_EXPOSURE, cfg.exposure)
        self._grabber = _LatestFrameGrabber(self._cap)

        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or cfg.width
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or cfg.height

        self._landmarker = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=cfg.max_hands,
                min_hand_detection_confidence=cfg.min_detection_confidence,
                min_tracking_confidence=cfg.min_tracking_confidence,
            )
        )
        self.meta = SourceMeta(
            name="camera",
            fps_nominal=float(cfg.fps),
            width=width,
            height=height,
            model=f"mediapipe_hands@{mp.__version__}",
            recorded=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            notes=f"device={device} mirror={mirror}",
        )
        self._start = time.monotonic()
        self._last_stamp = -1
        self.timings = StageTimings()

    def frames(self) -> Iterator[Frame]:
        seq = 0
        while True:
            if self.max_frames is not None and seq >= self.max_frames:
                return
            t_capture = time.monotonic()
            bgr, grabbed_at = self._grabber.latest()
            t_captured = time.monotonic()
            if bgr is None:
                continue
            # The frame's own capture instant, not "now" — otherwise every latency measurement
            # downstream silently excludes however long the frame sat waiting.
            t_ms = (grabbed_at - self._start) * 1000.0
            if self.max_seconds is not None and (t_captured - self._start) > self.max_seconds:
                return
            if self.mirror:
                bgr = cv2.flip(bgr, 1)

            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            t_converted = time.monotonic()
            # detect_for_video demands STRICTLY increasing integer milliseconds and raises
            # ValueError otherwise. Truncating a monotonic float is only non-decreasing, so two
            # frames inside the same millisecond would crash the capture loop. Cheap to guard,
            # very annoying to diagnose in the field.
            stamp = max(int(t_ms), self._last_stamp + 1)
            self._last_stamp = stamp
            result = self._landmarker.detect_for_video(image, stamp)
            t_inferred = time.monotonic()

            hands: list[Hand] = []
            for i, landmarks in enumerate(result.hand_landmarks or []):
                label = "Right"
                score = 1.0
                if result.handedness and i < len(result.handedness) and result.handedness[i]:
                    label = result.handedness[i][0].category_name
                    score = float(result.handedness[i][0].score)
                hands.append(
                    Hand(
                        handedness=_handedness(label),
                        tracking_score=score,
                        landmarks=tuple((float(p.x), float(p.y), float(p.z)) for p in landmarks),
                    )
                )

            frame = Frame(
                seq=seq,
                t_ms=t_ms,
                width=self.meta.width,
                height=self.meta.height,
                hands=tuple(hands),
            )
            t_assembled = time.monotonic()

            self.timings.capture.append((t_captured - t_capture) * 1000)
            self.timings.convert.append((t_converted - t_captured) * 1000)
            self.timings.inference.append((t_inferred - t_converted) * 1000)
            self.timings.assemble.append((t_assembled - t_inferred) * 1000)

            yield frame
            seq += 1

    def close(self) -> None:
        try:
            self._grabber.close()
        finally:
            try:
                self._landmarker.close()
            finally:
                self._cap.release()
