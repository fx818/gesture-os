#!/usr/bin/env python3
"""Pick the camera exposure that maximises hand DETECTION, not brightness.

A fixed exposure cannot work: the right value depends on ambient light, and this project has
already been burned twice by that. Exposure 200 gave 12/12 detection in a dark backlit room and
0/12 once the room light came on — over-exposed, washed out, and motion-blurring the hand during
exactly the movement we want to capture.

Detection rate is the objective because it is the thing we actually need. Brightness is not
monotonic with it: too dark loses skin tone, too bright loses contrast and adds motion blur.

    python tools/calibrate_camera.py [--write]

Hold a hand in frame, moving a little, for the duration.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import mediapipe as mp  # noqa: E402
import numpy as np  # noqa: E402
from mediapipe.tasks.python import BaseOptions, vision  # noqa: E402

CANDIDATES = (0, 20, 40, 60, 80, 120, 160, 200, 300)  # 0 = auto
FRAMES = 12


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write the winner into config/default.toml")
    ap.add_argument("--device", type=int, default=0)
    args = ap.parse_args()

    lm = vision.HandLandmarker.create_from_options(
        vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(REPO / "models" / "hand_landmarker.task")),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=1,
        )
    )
    print("Hold a hand in frame, moving slightly, until this finishes.\n")
    print(f"  {'exposure':<12} {'brightness':>10} {'contrast':>9} {'detection':>10}")

    results = []
    for exposure in CANDIDATES:
        cap = cv2.VideoCapture(args.device)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if exposure > 0:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
            cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        else:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
        for _ in range(18):
            cap.read()

        seen = 0
        means: list[float] = []
        stds: list[float] = []
        for _ in range(FRAMES):
            ok, frame = cap.read()
            if not ok:
                continue
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            means.append(float(grey.mean()))
            stds.append(float(grey.std()))
            img = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(cv2.cvtColor(cv2.flip(frame, 1), cv2.COLOR_BGR2RGB)),
            )
            seen += bool(lm.detect(img).hand_landmarks)
        cap.release()

        label = "auto" if exposure == 0 else str(exposure)
        print(f"  {label:<12} {np.mean(means):>10.1f} {np.mean(stds):>9.1f} {seen:>7}/{FRAMES}")
        results.append((seen, float(np.mean(stds)), exposure))

    lm.close()
    # Best detection; ties broken toward the SHORTEST exposure that still detects reliably.
    #
    # Not toward contrast, which was the first version and is wrong here: this sweep is measured
    # on a hand held STILL, so it cannot see motion blur, and a longer exposure blurs exactly the
    # fast swipes the system exists to detect. Measured on this machine, 160 / 200 / 300 all
    # scored 12/12 while a static image — 160 is the one that will still resolve a moving hand.
    results.sort(key=lambda r: (-r[0], r[2] if r[2] > 0 else 10**6))
    best_seen, _, best = results[0]
    print(f"\nbest: exposure = {best or 'auto'}  ({best_seen}/{FRAMES} detected)")
    if best_seen < FRAMES // 2:
        print("WARNING: nothing detected reliably at any exposure. Check that a hand is in frame,")
        print("         and that the light is in FRONT of you rather than behind.")
        return 1

    if args.write:
        path = REPO / "config" / "default.toml"
        text = path.read_text()
        import re

        text = re.sub(r"^exposure = \d+$", f"exposure = {best}", text, flags=re.M)
        path.write_text(text)
        print(f"wrote exposure = {best} to config/default.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
