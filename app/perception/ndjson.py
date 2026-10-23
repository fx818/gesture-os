"""Fixture format: one JSON object per frame, gzipped, with a .meta.json sidecar.

Landmarks, not video. Three reasons, all load-bearing:

  * it honours the scope doc's "no frames leave the machine" even for artefacts committed to git
  * a 60-second session is ~200 KB gzipped, so fixtures live in the repo
  * it doubles as the wire protocol for SubprocessLandmarkSource, which is the escape hatch if
    MediaPipe ever fails to import on this Python (ADR-0005)

Coordinates are normalized, never pixels — so a fixture recorded on /dev/video0 at 640x480 also
validates a 1080p camera.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterator

from app.perception.source import SourceMeta
from app.types import Frame, Hand, Handedness


def _open(path: Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def frame_to_dict(f: Frame) -> dict:
    return {
        "seq": f.seq,
        # NOT rounded: time is data (see CLAUDE.md), and a recording must reproduce
        # the session that produced it exactly. Coordinates below are rounded because
        # 5dp is under the landmark model's noise floor and there are 63 of them per hand.
        "t_ms": f.t_ms,
        "w": f.width,
        "h": f.height,
        "hands": [
            {
                "h": hand.handedness.value,
                "s": round(hand.tracking_score, 4),
                "lm": [[round(c, 5) for c in pt] for pt in hand.landmarks],
            }
            for hand in f.hands
        ],
    }


def frame_from_dict(d: dict) -> Frame:
    return Frame(
        seq=int(d["seq"]),
        t_ms=float(d["t_ms"]),
        width=int(d["w"]),
        height=int(d["h"]),
        hands=tuple(
            Hand(
                handedness=Handedness(h["h"]),
                tracking_score=float(h["s"]),
                landmarks=tuple(tuple(float(c) for c in pt) for pt in h["lm"]),
            )
            for h in d["hands"]
        ),
    )


def meta_path(path: Path) -> Path:
    name = path.name
    for suffix in (".ndjson.gz", ".ndjson"):
        if name.endswith(suffix):
            return path.with_name(name[: -len(suffix)] + ".meta.json")
    return path.with_suffix(".meta.json")


class NdjsonWriter:
    def __init__(self, path: Path, meta: SourceMeta) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = _open(self.path, "w")
        self._meta = meta
        self._count = 0

    def write(self, frame: Frame) -> None:
        self._fh.write(json.dumps(frame_to_dict(frame), separators=(",", ":")) + "\n")
        self._count += 1

    def close(self) -> None:
        self._fh.close()
        meta = asdict(self._meta)
        meta["frames"] = self._count
        meta_path(self.path).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def read_meta(path: Path) -> SourceMeta:
    mp = meta_path(Path(path))
    if not mp.exists():
        return SourceMeta(name=Path(path).stem, fps_nominal=0.0, width=0, height=0)
    d = json.loads(mp.read_text(encoding="utf-8"))
    d.pop("frames", None)
    d["segments"] = tuple(d.get("segments", ()))
    return SourceMeta(**d)


def read_frames(path: Path) -> Iterator[Frame]:
    with _open(Path(path), "r") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield frame_from_dict(json.loads(line))


class FileLandmarkSource:
    """Replay. `realtime=False` (the default, and what tests use) runs as fast as the CPU allows;
    `realtime=True` paces to the recorded timestamps for demos."""

    def __init__(self, path: Path | str, *, realtime: bool = False) -> None:
        self.path = Path(path)
        self.realtime = realtime
        self.meta = read_meta(self.path)

    def frames(self) -> Iterator[Frame]:
        if not self.realtime:
            yield from read_frames(self.path)
            return

        import time

        start = time.monotonic()
        first: float | None = None
        for frame in read_frames(self.path):
            if first is None:
                first = frame.t_ms
            target = (frame.t_ms - first) / 1000.0
            drift = target - (time.monotonic() - start)
            if drift > 0:
                time.sleep(drift)
            yield frame

    def close(self) -> None:
        return None
