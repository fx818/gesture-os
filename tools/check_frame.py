#!/usr/bin/env python3
"""Live 'is your hand visible?' check. Prints a bar per frame so you can position yourself."""
import sys, time
from pathlib import Path
# Resolve the repo from THIS file, not an absolute path — the project moved once
# already and a hardcoded path silently breaks the moment it does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import load
from app.perception.backends.mediapipe_camera import MediaPipeCameraSource

device = int(sys.argv[1]) if len(sys.argv) > 1 else 0
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
cfg = load(use_env=False).perception
src = MediaPipeCameraSource(cfg, device=device, max_seconds=secs)
seen = total = 0
try:
    for f in src.frames():
        total += 1
        if f.hands:
            seen += 1
            h = f.hands[0]
            x, y = h.landmarks[0][0], h.landmarks[0][1]
            print(f"  HAND  wrist=({x:.2f},{y:.2f})  score={h.tracking_score:.2f}", flush=True)
        elif total % 10 == 0:
            print("  (no hand)", flush=True)
finally:
    src.close()
print(f"\ndevice {device}: {seen}/{total} frames with a hand")
