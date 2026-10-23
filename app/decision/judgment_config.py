"""Loader for config/judgment/points.yaml. Separate from app/config.py because this file has a
different reviewer and a different review cadence: thresholds are tuned from data, instructions are
edited by a human reading them as prose."""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from app.decision.questions import ChoiceQ, NoulQ, PointId, Question, ScoreQ

POINTS_PATH = Path(__file__).resolve().parents[2] / "config" / "judgment" / "points.yaml"


class JudgmentConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FallbackRule:
    app_class: str
    confidence: float
    pattern: str


@dataclass(frozen=True, slots=True)
class FallbackConfig:
    rules: tuple[FallbackRule, ...] = ()
    title_confidence_factor: float = 0.65
    ambiguous_confidence_max: float = 0.6
    title_refine_factor: float = 0.9
    # Point F's fallback weights. Kept here rather than in code for the same reason as point A's
    # rule table: they are tuning, and calibration must be able to reach them.
    values: Mapping[str, float] = field(default_factory=dict)

    def value(self, key: str, default: float = 0.0) -> float:
        return float(self.values.get(key, default))


@dataclass(frozen=True, slots=True)
class PointConfig:
    point: PointId
    enabled: bool
    rev: int
    act_threshold: float
    confirm_threshold: float
    timeout_ms: float
    cache_ttl_s: float
    max_state_chars: int
    max_field_chars: int
    on_low_confidence: str
    noul_true_threshold: float = 0.5
    questions: Mapping[str, Question] = field(default_factory=dict)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)


@dataclass(frozen=True, slots=True)
class JudgmentConfig:
    points: Mapping[PointId, PointConfig]
    rate_limit_per_min: int

    def point(self, point: PointId) -> PointConfig:
        if point not in self.points:
            raise JudgmentConfigError(f"points.yaml has no entry for '{point.value}'")
        return self.points[point]


def _build_question(key: str, spec: Mapping[str, Any]) -> Question:
    kind = spec.get("kind")
    instructions = (spec.get("instructions") or "").strip()
    if not instructions:
        raise JudgmentConfigError(f"question '{key}' has no instructions")
    if kind == "choice":
        options = spec.get("options") or {}
        if len(options) < 2:
            raise JudgmentConfigError(f"choice '{key}' needs at least two options")
        return ChoiceQ(instructions=instructions, options={str(k): str(v) for k, v in options.items()})
    if kind == "score":
        return ScoreQ(instructions=instructions, levels=[str(x) for x in spec.get("levels") or []])
    if kind == "noul":
        return NoulQ(
            instructions=instructions,
            when_true=spec.get("when_true"),
            when_false=spec.get("when_false"),
        )
    raise JudgmentConfigError(f"question '{key}' has unknown kind {kind!r}")


def _clean_pattern(pattern: str) -> str:
    """Undo YAML folded-scalar wrapping without eating real spaces.

    A `>-` scalar joins wrapped lines with a space, so an alternation broken after `|` arrives as
    "...goland| rubymine|...". Collapsing ALL whitespace fixes that and silently breaks the
    multi-word alternatives — "code oss" becomes "codeoss" — so only whitespace adjacent to a
    separator is removed.
    """
    collapsed = re.sub(r"\s+", " ", pattern).strip()
    return re.sub(r"\s*\|\s*", "|", collapsed)


def _build_fallback(spec: Mapping[str, Any]) -> FallbackConfig:
    raw_rules = spec.get("rules") or []
    rules = tuple(
        FallbackRule(
            app_class=str(r["class"]),
            confidence=float(r["confidence"]),
            pattern=_clean_pattern(str(r["pattern"])),
        )
        for r in raw_rules
    )
    return FallbackConfig(
        rules=rules,
        title_confidence_factor=float(spec.get("title_confidence_factor", 0.65)),
        ambiguous_confidence_max=float(spec.get("ambiguous_confidence_max", 0.6)),
        title_refine_factor=float(spec.get("title_refine_factor", 0.9)),
        values={
            k: float(v)
            for k, v in spec.items()
            if k not in {"rules", "title_confidence_factor", "ambiguous_confidence_max",
                         "title_refine_factor"}
            and isinstance(v, (int, float))
        },
    )


def load(path: Path = POINTS_PATH) -> JudgmentConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = raw.get("defaults") or {}
    points: dict[PointId, PointConfig] = {}

    for name, spec in (raw.get("points") or {}).items():
        try:
            point = PointId(name)
        except ValueError as e:
            raise JudgmentConfigError(f"unknown point id '{name}' in points.yaml") from e
        spec = spec or {}

        def pick(key: str, cast=float):
            return cast(spec.get(key, defaults.get(key)))

        questions = {
            qk: _build_question(qk, qs) for qk, qs in (spec.get("questions") or {}).items()
        }
        enabled = bool(spec.get("enabled", False))
        if enabled and not questions:
            raise JudgmentConfigError(f"point '{name}' is enabled but defines no questions")

        points[point] = PointConfig(
            point=point,
            enabled=enabled,
            rev=int(spec.get("rev", 1)),
            act_threshold=pick("act_threshold"),
            confirm_threshold=pick("confirm_threshold"),
            timeout_ms=pick("timeout_ms"),
            cache_ttl_s=pick("cache_ttl_s"),
            max_state_chars=pick("max_state_chars", int),
            max_field_chars=pick("max_field_chars", int),
            on_low_confidence=str(spec.get("on_low_confidence", defaults.get("on_low_confidence"))),
            noul_true_threshold=pick("noul_true_threshold"),
            questions=questions,
            fallback=_build_fallback(spec.get("fallback") or {}),
        )

    missing = set(PointId) - set(points)
    if missing:
        raise JudgmentConfigError(
            f"points.yaml is missing {sorted(p.value for p in missing)} — every point must be "
            f"listed even if disabled, so the file stays the full map of the Jev surface"
        )

    return JudgmentConfig(
        points=points, rate_limit_per_min=int(defaults.get("rate_limit_per_min", 300))
    )
