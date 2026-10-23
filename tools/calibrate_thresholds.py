#!/usr/bin/env python3
"""P5.6 — derive arbitration thresholds from recorded fixtures instead of guessing them.

ADR-0007 is the reason this exists: the shipped thresholds were invented to sit above a synthetic
generator whose speed I also invented, and a real swipe turned out to run 3-20x faster. 91% of the
frames in a real swipe clear `gross.speed`, which means that threshold is not separating anything.

Method, deliberately the same shape as the Jev point A calibration in
`docs/verification/p1-calibration.md`: build the distribution of each feature over POSITIVE
fixtures and over NEGATIVE ones, and place the threshold where they separate. A threshold derived
from positives alone fits itself and tells you nothing about what must not fire.

Classification is PER MODE, not global. A fixture is a positive for one mode and a negative for
others: `tremor-high` is a precision positive (the accessibility case — it must still track) and a
gross negative (it must never fire a window command). Lumping every non-negative fixture together
produced a meaningless answer the first time this ran, because `pose-hold` and `pinch-clicks` were
being counted as evidence about swipe thresholds.

    python tools/calibrate_thresholds.py [--write]
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.config import load  # noqa: E402
from app.features.extract import ExtractState, extract  # noqa: E402
from app.perception.ndjson import FileLandmarkSource, read_meta  # noqa: E402

SESSIONS = REPO / "fixtures" / "sessions"
# Per-mode ground truth. `None` means the fixture says nothing useful about that mode.
#   True  = this gesture SHOULD activate the mode
#   False = this gesture MUST NOT activate the mode
LABELS: dict[str, dict[str, bool]] = {
    "swipe-left":         {"gross": True,  "precision": False},
    "swipe-right":        {"gross": True,  "precision": False},
    "swipe-left-real":    {"gross": True,  "precision": False},
    "swipe-right-real":   {"gross": True,  "precision": False},
    # UNLABELLED FOR GROSS — this fixture does not contain what its name claims.
    # Measured 2026-09-18: the palm sweeps x=0.66 -> 0.11 -> 0.66 twice, 0.562 of frame width,
    # p90 speed 6.56 and p90 coherence 0.99. Those are swipe trajectories, not idle drift; on
    # every feature the gross guard reads it scores HIGHER than `live-swipe-check`, a recording
    # of a deliberate swipe. No threshold can separate them because there is nothing to separate.
    # Tuning to suppress it cost a real positive, so it is excluded from the gross gate instead.
    #
    # THIS LEAVES A HOLE. It was the corpus's only negative with an actively moving hand
    # (coffee-cup, live-desk-6s and neg-typing/neg-reach contain no hands at all; rest-60s and
    # pose-hold are near-motionless). `hover-at-threshold` is the closest survivor — p90 speed
    # 3.99 but only 0.106 travel — and it is the shape the replacement needs: a hand that moves
    # FAST without going anywhere. Re-record before trusting the gross thresholds. See ADR-0011.
    "neg-idle-motion":    {"precision": False},
    "precision-real":     {"gross": False, "precision": True},
    "pinch-real":         {"gross": False, "precision": True},
    "panic-real":         {"gross": False, "precision": False},
    "precision-trace":    {"gross": False, "precision": True},
    "pinch-clicks":       {"gross": False, "precision": True},
    "tremor-high":        {"gross": False, "precision": True},
    "pose-hold":          {"gross": False},
    "two-hand-panic":     {"gross": False, "precision": False},
    "rest-60s":           {"gross": False, "precision": False},
    "coffee-cup":         {"gross": False, "precision": False},
    "hover-at-threshold": {"gross": False, "precision": False},
    "live-desk-6s":       {"gross": False, "precision": False},
    "neg-typing":         {"gross": False, "precision": False},
    "neg-reach":          {"gross": False, "precision": False},
}


def label_for(name: str, mode: str) -> bool | None:
    return LABELS.get(name, {}).get(mode)


def features_of(path: Path, cfg):
    es = ExtractState()
    rows = []
    for frame in FileLandmarkSource(path).frames():
        es, ff = extract(es, frame, cfg.precision)
        h = ff.right or ff.left
        if h is not None and h.palm_speed > 0.0:
            rows.append((h.palm_speed, h.palm_dir_coherence, h.openness, h.index_extension))
    return rows


def pct(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * q))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--mode", default="gross", choices=["gross", "precision"])
    args = ap.parse_args()
    cfg = load(use_env=False)

    pos: dict[str, list] = {}
    neg: dict[str, list] = {}
    unlabelled: list[str] = []
    synthetic = real = 0

    for path in sorted(SESSIONS.glob("*.ndjson.gz")):
        name = path.name.split(".")[0]
        rows = features_of(path, cfg)
        if not rows:
            continue
        meta = read_meta(path)
        if meta.model == "synthetic":
            synthetic += 1
        else:
            real += 1
        label = label_for(name, args.mode)
        if label is None:
            unlabelled.append(name)
        elif label:
            pos[name] = rows
        else:
            neg[name] = rows

    print(f"calibrating '{args.mode}' — {len(pos)} positive, {len(neg)} negative fixtures "
          f"({real} recorded, {synthetic} synthetic)")
    if unlabelled:
        print(f"  (ignored, says nothing about {args.mode}: {', '.join(unlabelled)})")
    if real == 0:
        print("\nWARNING: every fixture is synthetic. Thresholds derived from these describe my")
        print("         generators, not a person. See ADR-0007.")

    print(f"\n  {'fixture':<22} {'n':>5} {'speed p50':>10} {'speed p90':>10} {'coh p50':>8}")
    for lbl, group in (("POSITIVE", pos), ("NEGATIVE", neg)):
        if not group:
            continue
        print(f"  -- {lbl} --")
        for name, rows in sorted(group.items()):
            sp = [r[0] for r in rows]
            co = [r[1] for r in rows]
            print(f"  {name:<22} {len(rows):>5} {statistics.median(sp):>10.2f} "
                  f"{pct(sp, 0.9):>10.2f} {statistics.median(co):>8.2f}")

    pos_speed = [r[0] for rows in pos.values() for r in rows]
    neg_speed = [r[0] for rows in neg.values() for r in rows]
    pos_coh = [r[1] for rows in pos.values() for r in rows]
    neg_coh = [r[1] for rows in neg.values() for r in rows]

    if not pos_speed or not neg_speed:
        print("\nnot enough data on both sides to recommend anything")
        return 1

    if args.mode != "gross":
        print("\nonly 'gross' has a threshold recommender so far; the table above is the input "
              "for tuning precision by hand.")
        return 0

    # Above the negatives' 95th percentile, below the positives' median. Asymmetric on purpose:
    # a false positive fires a window command nobody asked for, while a missed gesture is simply
    # repeated.
    neg95 = pct(neg_speed, 0.95)
    pos50 = statistics.median(pos_speed)
    print("\nrecommendations")
    if neg95 >= pos50:
        print(f"  gross.speed        NO CLEAN SPLIT — negatives reach {neg95:.2f}, "
              f"positives sit at {pos50:.2f}")
        speed_rec = cfg.gross.speed
    else:
        speed_rec = round(neg95 + (pos50 - neg95) * 0.35, 2)
        print(f"  gross.speed        {cfg.gross.speed}  ->  {speed_rec}    "
              f"(negatives p95 {neg95:.2f}, positives p50 {pos50:.2f})")

    coh_rec = round(max(0.5, min(pct(pos_coh, 0.25), 0.95)), 2)
    print(f"  gross.coherence    {cfg.gross.coherence}  ->  {coh_rec}    "
          f"(positives p25 {pct(pos_coh, 0.25):.2f}, negatives p50 {statistics.median(neg_coh):.2f})")

    for label, thr in (("current", cfg.gross.speed), ("recommended", speed_rec)):
        hit = sum(1 for s in pos_speed if s > thr) / len(pos_speed)
        false = sum(1 for s in neg_speed if s > thr) / len(neg_speed)
        print(f"  at speed={thr:<6} ({label:<11}) {hit:.0%} of positive frames clear it, "
              f"{false:.0%} of negative frames do")

    if args.write:
        path = REPO / "config" / "default.toml"
        import re

        text = path.read_text()
        text = re.sub(r"^speed = [\d.]+$", f"speed = {speed_rec}", text, count=1, flags=re.M)
        text = re.sub(r"^coherence = [\d.]+$", f"coherence = {coh_rec}", text, count=1, flags=re.M)
        path.write_text(text)
        print(f"\nwrote gross.speed={speed_rec} gross.coherence={coh_rec}")
        print("REVIEW `python main.py golden` afterwards — thresholds change behaviour.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
