"""Pose templates and matching.

A pose is a 15-element vector of finger flexion angles, which is translation- and scale-invariant
by construction (see features/extract.py). Matching is cosine similarity against a stored library.

Lives at the bottom of the stack beside `naming` and `intents`, because both `arbitration` (whose
macro guard needs to know whether the current pose matches anything) and `routing` (which needs to
know WHICH pose, to fire its macro) depend on it, and they are on different layers.

The library is per-user and starts EMPTY on purpose. Hand proportions and the way a person forms a
fist vary enough that shipping my idea of "a fist" would be worse than shipping nothing: the user
records their own with `record-pose`. Until then, macro mode falls back to a coarse openness
heuristic and says so.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIBRARY = REPO_ROOT / "config" / "poses.json"

JOINT_ANGLE_COUNT = 15


@dataclass(frozen=True, slots=True)
class PoseTemplate:
    name: str
    angles: tuple[float, ...]
    openness: float
    samples: int = 1
    note: str = ""

    def __post_init__(self) -> None:
        if len(self.angles) != JOINT_ANGLE_COUNT:
            raise ValueError(
                f"pose '{self.name}' has {len(self.angles)} angles, expected {JOINT_ANGLE_COUNT}"
            )


@dataclass(frozen=True, slots=True)
class PoseMatch:
    name: str
    similarity: float

    @staticmethod
    def none() -> PoseMatch:
        return PoseMatch(name="", similarity=-1.0)

    @property
    def matched(self) -> bool:
        return bool(self.name)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Plain cosine similarity, clamped to [0, 1].

    **Not used for pose matching** — see `similarity()`. Kept because the scope doc names it, and
    because the measurement that ruled it out is worth being able to reproduce: against a recorded
    fist template, every fixture in the corpus scored 0.85-0.97, and the one fixture that actually
    IS a fist scored lowest of all. Joint-angle vectors are dominated by a common "this is a hand"
    component that makes every pose near-parallel to every other.
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Pose similarity: cosine of the MEAN-CENTRED vectors, i.e. Pearson correlation.

    Centring removes the common component that makes all hands look alike, and it is the
    difference between a metric that works and one that does not. Measured against a recorded
    fist template across the whole fixture corpus:

        metric        fist    resting   pointing   open palm   pinch     usable range
        cosine       0.853     0.966     0.922      0.962      0.961     0.11
        correlation  0.333    -0.076     0.336     -0.519     -0.716     1.06

    Cosine ranked the actual fist LOWEST. Correlation separates cleanly and its sign is
    meaningful: a negative score means the flexion pattern is inverted, i.e. an open hand
    against a closed template.

    Returns -1..1, not 0..1, because the negative half carries information.
    """
    if len(a) != len(b) or not a:
        return 0.0
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    da = [x - ma for x in a]
    db = [y - mb for y in b]
    na = math.sqrt(sum(x * x for x in da))
    nb = math.sqrt(sum(y * y for y in db))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(da, db)) / (na * nb)))


@dataclass(frozen=True, slots=True)
class PoseLibrary:
    templates: tuple[PoseTemplate, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.templates

    def best(self, angles: Sequence[float]) -> PoseMatch:
        best = PoseMatch.none()
        for template in self.templates:
            score = similarity(angles, template.angles)
            if score > best.similarity:
                best = PoseMatch(template.name, score)
        return best

    def get(self, name: str) -> PoseTemplate | None:
        for t in self.templates:
            if t.name == name:
                return t
        return None

    # -- persistence ---------------------------------------------------------------

    @classmethod
    def load(cls, path: Path = DEFAULT_LIBRARY) -> PoseLibrary:
        if not Path(path).exists():
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            templates=tuple(
                PoseTemplate(
                    name=t["name"],
                    angles=tuple(float(x) for x in t["angles"]),
                    openness=float(t.get("openness", 0.0)),
                    samples=int(t.get("samples", 1)),
                    note=t.get("note", ""),
                )
                for t in data.get("poses", [])
            )
        )

    def save(self, path: Path = DEFAULT_LIBRARY) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "_comment": "Per-user pose templates. Record with: python main.py record-pose <name>",
                    "poses": [
                        {
                            "name": t.name,
                            "angles": [round(a, 5) for a in t.angles],
                            "openness": round(t.openness, 5),
                            "samples": t.samples,
                            "note": t.note,
                        }
                        for t in self.templates
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def with_template(self, template: PoseTemplate) -> PoseLibrary:
        """Replace by name if present, else append. Re-recording a pose should improve it, not
        create a second entry that competes with the first."""
        others = tuple(t for t in self.templates if t.name != template.name)
        return PoseLibrary(templates=others + (template,))


def average(name: str, samples: Sequence[Sequence[float]], openness: Sequence[float], note: str = "") -> PoseTemplate:
    """Build a template from several frames of a held pose.

    Averaging matters: a single frame bakes in whatever tracking noise that frame had, and the
    resulting template then matches that noise as much as the pose.
    """
    if not samples:
        raise ValueError("no samples")
    n = len(samples)
    angles = tuple(sum(s[i] for s in samples) / n for i in range(JOINT_ANGLE_COUNT))
    return PoseTemplate(
        name=name,
        angles=angles,
        openness=sum(openness) / len(openness) if openness else 0.0,
        samples=n,
        note=note,
    )
