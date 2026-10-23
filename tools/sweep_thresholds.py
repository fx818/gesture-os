#!/usr/bin/env python3
"""End-to-end threshold sweep: calibrate on what the ENGINE emits, not on frame statistics.

`calibrate_thresholds.py` compares per-frame distributions, and that turned out to be the wrong
unit. It reported that only 4% of negative frames exceeded `gross.speed` — which sounds decisive —
while the engine was still firing two spurious workspace switches on the same fixture. The engine
decides over a 250ms window with `for_all_frames`, streaks, dwell and refractory on top, so a
frame-level margin says very little about whether a gesture fires.

This runs the real pipeline over every labelled fixture at each candidate threshold pair and
counts actual intents. Slower, and the only number that means anything.

    python tools/sweep_thresholds.py [--write]
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.config import load  # noqa: E402
from app.effectors.backends import recording  # noqa: E402
from app.effectors.ports import EffectorSet  # noqa: E402
from app.perception.ndjson import FileLandmarkSource  # noqa: E402
from app.runtime.pipeline import run_pipeline  # noqa: E402

sys.path.insert(0, str(REPO / "tools"))
from calibrate_thresholds import LABELS, SESSIONS  # noqa: E402

SPEEDS = (1.8, 2.5, 3.0, 3.5, 4.0, 5.0)
COHERENCES = (0.70, 0.80, 0.88, 0.94)


def fire_count(path: Path, cfg) -> int:
    journal = recording.Journal()
    fx = EffectorSet(
        pointer=recording.RecordingPointerSink(journal), keys=recording.RecordingKeySink(journal)
    )
    result = run_pipeline(FileLandmarkSource(path), fx, cfg=cfg, watchdog=False)
    return sum(1 for e in result.intents if e.intent.kind in ("SwitchWindow", "SendToWorkspace", "SendToMonitor"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    base = load(use_env=False)
    fixtures = []
    for path in sorted(SESSIONS.glob("*.ndjson.gz")):
        name = path.name.split(".")[0]
        label = LABELS.get(name, {}).get("gross")
        if label is not None:
            fixtures.append((name, path, label))

    positives = [f for f in fixtures if f[2]]
    negatives = [f for f in fixtures if not f[2]]
    print(f"{len(positives)} positive, {len(negatives)} negative fixtures\n")
    print(f"  {'speed':>6} {'coh':>5} | {'gestures detected':>18} | {'FALSE FIRES':>12} |  verdict")

    best = None
    for speed in SPEEDS:
        for coherence in COHERENCES:
            cfg = dataclasses.replace(
                base, gross=dataclasses.replace(base.gross, speed=speed, coherence=coherence)
            )
            hits = sum(1 for _, p, _ in positives if fire_count(p, cfg) > 0)
            false = sum(fire_count(p, cfg) for _, p, _ in negatives)
            # A false positive fires a command nobody asked for; a missed gesture is repeated.
            # So: zero false fires first, then as many gestures detected as possible.
            score = (false == 0, hits, -false)
            verdict = "clean" if false == 0 else ""
            print(f"  {speed:>6.1f} {coherence:>5.2f} | {hits:>6}/{len(positives):<11} | "
                  f"{false:>12} |  {verdict}")
            if best is None or score > best[0]:
                best = (score, speed, coherence, hits, false)

    _, speed, coherence, hits, false = best
    print(f"\nbest: gross.speed={speed} gross.coherence={coherence} "
          f"-> {hits}/{len(positives)} gestures detected, {false} false fires")
    if false:
        print("  NOTE: no pair eliminated false fires. Speed and coherence alone cannot separate")
        print("        these; the engine needs another discriminator.")

    if args.write and not false:
        import re

        path = REPO / "config" / "default.toml"
        text = path.read_text()
        text = re.sub(r"^speed = [\d.]+", f"speed = {speed}", text, count=1, flags=re.M)
        text = re.sub(r"^coherence = [\d.]+", f"coherence = {coherence}", text, count=1, flags=re.M)
        path.write_text(text)
        print(f"\nwrote gross.speed={speed} gross.coherence={coherence}")
        print("REVIEW `python main.py golden` — thresholds change behaviour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
