"""Golden intent streams.

The highest-value test asset in the project: a behaviour change shows up as a reviewable diff in
the commit rather than as "it feels flickery now". Intents are the second recordable seam
(landmarks in, intents out), which is why arbitration emits value objects instead of calling
effectors directly.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path

from app.effectors.backends import recording
from app.effectors.ports import EffectorSet
from app.perception.ndjson import FileLandmarkSource
from app.runtime.pipeline import PipelineResult, run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSIONS = REPO_ROOT / "fixtures" / "sessions"
GOLDEN = REPO_ROOT / "fixtures" / "golden"

# Floats are rounded before comparison: the engine is deterministic, but a golden file that
# encoded full double precision would turn any harmless refactor into a diff.
PRECISION = 3


def _args(intent) -> dict:
    if not is_dataclass(intent):
        return {}
    out = {}
    for f in fields(intent):
        if f.name == "requires":
            continue
        v = getattr(intent, f.name)
        out[f.name] = round(v, PRECISION) if isinstance(v, float) else getattr(v, "value", v)
    return out


def render(result: PipelineResult) -> str:
    lines = []
    for t_ms, mode in result.transitions:
        lines.append(
            json.dumps({"t_ms": round(t_ms, PRECISION), "event": "mode", "mode": mode.value},
                       sort_keys=True)
        )
    for e in result.intents:
        lines.append(
            json.dumps(
                {
                    "t_ms": round(e.t_ms, PRECISION),
                    "event": "intent",
                    "mode": e.mode.value,
                    "intent": e.intent.kind,
                    "args": _args(e.intent),
                },
                sort_keys=True,
            )
        )
    lines.sort(key=lambda s: (json.loads(s)["t_ms"], json.loads(s)["event"]))
    return "\n".join(lines) + ("\n" if lines else "")


def replay_fixture(path: Path) -> PipelineResult:
    journal = recording.Journal()
    effectors = EffectorSet(
        pointer=recording.RecordingPointerSink(journal),
        keys=recording.RecordingKeySink(journal),
        windows=recording.RecordingWindowManager(journal),
    )
    return run_pipeline(FileLandmarkSource(path), effectors)


def golden_path(fixture: Path) -> Path:
    return GOLDEN / (fixture.name.split(".")[0] + ".intents.ndjson")


def fixtures() -> list[Path]:
    return sorted(SESSIONS.glob("*.ndjson.gz"))


def check(fixture: Path) -> tuple[bool, str, str]:
    expected_path = golden_path(fixture)
    actual = render(replay_fixture(fixture))
    expected = expected_path.read_text(encoding="utf-8") if expected_path.exists() else ""
    return actual == expected, expected, actual


def update(fixture: Path) -> Path:
    path = golden_path(fixture)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(replay_fixture(fixture)), encoding="utf-8")
    return path
