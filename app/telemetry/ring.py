"""Rolling record of what the engine was doing, and its serialization to text.

Feeds Jev point F. The 2 seconds before a panic gesture are the most valuable data the system
produces: the user physically asserted "that was wrong", which is a label no amount of offline
analysis can manufacture.

The serializer is the interesting part. Jev is a text-only classifier that cannot count, do
arithmetic, or compare numbers reliably — documented weaknesses. So this does NOT hand it a table
of velocities and ask it to spot the anomaly. It renders the episode into plain descriptive
language and asks a closed-set question about it. Every number that matters is turned into a word
HERE, in code, where arithmetic is free and reliable.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from app.arbitration.state import ArbiterTrace
from app.intents import Intent
from app.types import FeatureFrame, ModeId

MISFIRE_DIR = Path.home() / ".local" / "share" / "gesture-os" / "misfires"

# How far back a panic gesture is assumed to be reacting to.
LOOKBACK_MS = 2000.0


@dataclass(frozen=True, slots=True)
class Episode:
    t_ms: float
    mode: ModeId
    trace: ArbiterTrace | None
    intents: tuple[Intent, ...]
    speed: float
    coherence: float
    openness: float


@dataclass
class EventRing:
    lookback_ms: float = LOOKBACK_MS
    events: deque[Episode] = field(default_factory=lambda: deque(maxlen=600))

    def push(
        self,
        t_ms: float,
        mode: ModeId,
        frame: FeatureFrame,
        trace: ArbiterTrace | None = None,
        intents: tuple[Intent, ...] = (),
    ) -> None:
        h = frame.right or frame.left
        self.events.append(
            Episode(
                t_ms=t_ms,
                mode=mode,
                trace=trace,
                intents=intents,
                speed=h.palm_speed if h else 0.0,
                coherence=h.palm_dir_coherence if h else 0.0,
                openness=h.openness if h else 0.0,
            )
        )

    def window(self, until_t_ms: float) -> list[Episode]:
        cutoff = until_t_ms - self.lookback_ms
        return [e for e in self.events if cutoff <= e.t_ms <= until_t_ms]


# --------------------------------------------------------------------------------------
# Rendering: numbers -> words, in code, before Jev ever sees it
# --------------------------------------------------------------------------------------


def _describe_speed(speed: float, gross_threshold: float) -> str:
    if speed < gross_threshold * 0.15:
        return "almost stationary"
    if speed < gross_threshold * 0.5:
        return "moving slowly"
    if speed < gross_threshold:
        return "moving moderately"
    if speed < gross_threshold * 2:
        return "moving fast"
    return "moving very fast"


def _describe_coherence(coherence: float, threshold: float) -> str:
    if coherence >= threshold:
        return "travelling in a straight, consistent direction"
    if coherence >= threshold * 0.6:
        return "travelling in a roughly consistent direction"
    return "changing direction erratically"


def _describe_pose(openness: float) -> str:
    if openness < 0.35:
        return "closed, like a fist"
    if openness < 0.65:
        return "partly closed"
    return "open, fingers spread"


def render_episode(episodes: list[Episode], cfg) -> dict[str, str]:
    """Build the Jev state for one misfire. Text only; no field is a raw measurement."""
    if not episodes:
        return {"summary": "no activity was recorded before the panic gesture"}

    start = episodes[0].t_ms
    timeline: list[str] = []
    last_mode: ModeId | None = None
    for e in episodes:
        if e.mode is not last_mode:
            secs = (e.t_ms - start) / 1000.0
            timeline.append(f"at {secs:.1f}s entered {e.mode.value} mode")
            last_mode = e.mode

    actions = [i.kind for e in episodes for i in e.intents]
    mid = episodes[len(episodes) // 2]

    # A near-miss is as diagnostic as the thing that fired: a mode that scored just under its
    # threshold throughout is a threshold problem, and one that oscillated is an ambiguity problem.
    near_misses: list[str] = []
    for e in episodes:
        if e.trace is None:
            continue
        top = e.trace.top()
        if top and e.trace.winner is not top[0] and top[1] > 0.5:
            near_misses.append(top[0].value)

    return {
        "what_the_user_did": "The user made the two-handed panic gesture, which means they judged "
        "that the system had just done something they did not intend.",
        "mode_timeline": "; ".join(timeline) or "the system stayed idle throughout",
        "actions_the_system_took": ", ".join(sorted(set(actions))) or "no action was taken",
        "hand_movement": _describe_speed(mid.speed, cfg.gross.speed),
        "hand_direction": _describe_coherence(mid.coherence, cfg.gross.coherence),
        "hand_shape": _describe_pose(mid.openness),
        "modes_that_nearly_activated": ", ".join(sorted(set(near_misses))) or "none",
    }


def dump(episodes: list[Episode], cfg, directory: Path = MISFIRE_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"misfire-{time.strftime('%Y%m%dT%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.json"
    path.write_text(
        json.dumps(
            {
                "recorded": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "state": render_episode(episodes, cfg),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def pending(directory: Path = MISFIRE_DIR) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("misfire-*.json") if not p.with_suffix(".verdict.json").exists())
