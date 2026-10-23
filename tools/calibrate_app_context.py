#!/usr/bin/env python3
"""P1.11 — set point A's confidence thresholds from data instead of from a guess.

Runs the corpus through the provider, buckets by reported confidence, and prints accuracy per
bucket. The question it answers is not "how accurate is Jev" but "at what confidence is Jev's
answer worth acting on automatically" — which is the only number `act_threshold` should be set from.

Read the disagreements before trusting the totals: the `expected` column is a human label and is
sometimes the thing that is wrong.

    python tools/calibrate_app_context.py [--offline] [--limit N] [--no-cache]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from app.decision.judgment_config import load as load_judgment  # noqa: E402
from app.decision.points import a_app_context as point_a  # noqa: E402
from app.decision.questions import PointId  # noqa: E402
from app.runtime.wiring import build_judgment_provider  # noqa: E402
from app.types import FocusInfo  # noqa: E402

CORPUS = REPO_ROOT / "fixtures" / "calibration" / "app_context.tsv"
BUCKETS = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 0.95), (0.95, 1.01))


def load_corpus(limit: int | None):
    rows = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        # A 5th tab-separated field is a free-text note (e.g. why a label was corrected).
        rows.append(tuple(p.strip() for p in parts[:4]))
    return rows[:limit] if limit else rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--show-misses", action="store_true", default=True)
    args = ap.parse_args()

    jcfg = load_judgment()
    pcfg = jcfg.point(PointId.A_APP_CONTEXT)
    provider = build_judgment_provider(
        jcfg, pcfg, force_offline=args.offline, use_cache=not args.no_cache
    )

    rows = load_corpus(args.limit)
    print(f"corpus: {len(rows)} rows · point A rev {pcfg.rev} · "
          f"{'offline (rules)' if args.offline else 'live'}\n")

    buckets: dict[tuple[float, float], list[bool]] = defaultdict(list)
    by_source: dict[str, list[bool]] = defaultdict(list)
    latencies: list[float] = []
    misses: list[tuple] = []
    text_entry_values: list[float] = []

    for i, (origin, app, title, expected) in enumerate(rows, 1):
        focus = FocusInfo(app, title, "frame", None, 0.0)
        t0 = time.monotonic()
        try:
            answers = provider.judge(point_a.build_request(focus, pcfg))
        except Exception as e:
            print(f"  [{i}/{len(rows)}] {app}: ERROR {type(e).__name__}: {e}")
            continue
        latencies.append((time.monotonic() - t0) * 1000)
        ctx = point_a.interpret(answers, pcfg)
        ok = ctx.app_class.value == expected

        for lo, hi in BUCKETS:
            if lo <= ctx.confidence < hi:
                buckets[(lo, hi)].append(ok)
                break
        by_source[ctx.source.value].append(ok)
        if "is_text_entry" in answers:
            text_entry_values.append(float(answers["is_text_entry"].value))
        if not ok:
            misses.append((origin, app, title, expected, ctx.app_class.value, ctx.confidence))
        if sys.stdout.isatty():
            print(f"\r  {i}/{len(rows)}", end="", flush=True)

    total = sum(len(v) for v in buckets.values())
    correct = sum(sum(v) for v in buckets.values())
    print(f"\r{' ' * 20}\r")

    print("accuracy by reported confidence")
    print(f"  {'bucket':<14} {'n':>4} {'correct':>8} {'accuracy':>9}")
    cumulative_n = cumulative_ok = 0
    for b in reversed(BUCKETS):
        v = buckets.get(b, [])
        if not v:
            continue
        cumulative_n += len(v)
        cumulative_ok += sum(v)
        print(f"  {b[0]:.2f}-{b[1]:<9.2f} {len(v):>4} {sum(v):>8} "
              f"{sum(v) / len(v):>8.1%}   (>= {b[0]:.2f}: {cumulative_ok}/{cumulative_n} = "
              f"{cumulative_ok / cumulative_n:.1%})")

    print(f"\noverall        {correct}/{total} = {correct / total:.1%}" if total else "")
    print("by source     ", {k: f"{sum(v)}/{len(v)}" for k, v in by_source.items()})
    if latencies:
        print(f"latency        p50 {statistics.median(latencies):.0f} ms · "
              f"p95 {sorted(latencies)[int(len(latencies) * 0.95)]:.0f} ms · "
              f"max {max(latencies):.0f} ms")

    if text_entry_values:
        spread = max(text_entry_values) - min(text_entry_values)
        print(f"\nis_text_entry  range {min(text_entry_values):.2f}-{max(text_entry_values):.2f} "
              f"(spread {spread:.2f}), median {statistics.median(text_entry_values):.2f}")
        if spread < 0.4:
            print("  ^ clustered near the uncertainty floor — this question is not separating. "
                  "Reword it against concrete situations, or delete it (ADR-0004).")

    if misses and args.show_misses:
        print(f"\ndisagreements ({len(misses)}) — check the label before blaming the model:")
        for origin, app, title, expected, got, conf in misses:
            print(f"  [{origin:<8}] {app:<22} {title[:44]:<46} want={expected:<15} "
                  f"got={got:<15} conf={conf:.2f}")

    print("\nSetting act_threshold: pick the lowest bucket whose accuracy you would accept as an")
    print("automatic action, then write it into config/judgment/points.yaml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
