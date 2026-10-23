"""Config loading. One surface, frozen, validated at load.

Layering: config/default.toml -> config/profiles/<user>.toml -> GESTURE_OS_* env -> CLI overrides.
Later layers override earlier ones key by key; nothing mutates default.toml.

The validation here is load-bearing, not decorative. `sustain[m] < enter[m]` for every mode is what
makes boundary flutter *unconfigurable* rather than merely unlikely — a bad calibration profile
fails at startup instead of in the user's hand.

Imports `types` only.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.poses import PoseLibrary
from app.types import ModeId

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "default.toml"
PROFILE_DIR = REPO_ROOT / "config" / "profiles"

ENV_PREFIX = "GESTURE_OS_"


class ConfigError(ValueError):
    """Raised at load time. Never caught by the runtime — a bad config must not start."""


@dataclass(frozen=True, slots=True)
class OneEuroConfig:
    min_cutoff: float
    beta: float
    d_cutoff: float


@dataclass(frozen=True, slots=True)
class ArbitrationConfig:
    enter: Mapping[ModeId, float]
    sustain: Mapping[ModeId, float]
    enter_frames: Mapping[ModeId, int]
    sustain_fraction: Mapping[ModeId, float]
    enter_fraction: Mapping[ModeId, float]
    hold_ms: Mapping[ModeId, float]
    min_dwell_ms: Mapping[ModeId, float]
    refractory_ms: Mapping[ModeId, float]
    idle_decay_ms: float
    window_span_ms: float
    window_min_frames: int


@dataclass(frozen=True, slots=True)
class GrossConfig:
    speed: float
    speed_sustain: float
    coherence: float


@dataclass(frozen=True, slots=True)
class PrecisionConfig:
    index_extension: float
    max_palm_speed: float
    max_palm_speed_sustain: float
    one_euro: OneEuroConfig
    pinch_click_close: float
    pinch_click_open: float


@dataclass(frozen=True, slots=True)
class SliderConfig:
    parameter: str
    pinch_max: float


@dataclass(frozen=True, slots=True)
class MacroConfig:
    max_speed: float
    sample_max_speed: float
    template_cosine_min: float
    template_similarity_max: float
    max_openness: float


@dataclass(frozen=True, slots=True)
class PanicConfig:
    require_both_hands: bool
    both_open_min: float
    max_speed: float
    hold_ms: float
    watchdog_hold_ms: float


@dataclass(frozen=True, slots=True)
class PerceptionConfig:
    width: int
    height: int
    fps: int
    model_complexity: int
    max_hands: int
    min_detection_confidence: float
    min_tracking_confidence: float
    exposure: int = 0


@dataclass(frozen=True, slots=True)
class LatencyConfig:
    precision_budget_ms: float
    discrete_budget_ms: float


@dataclass(frozen=True, slots=True)
class Config:
    arbitration: ArbitrationConfig
    gross: GrossConfig
    precision: PrecisionConfig
    macro: MacroConfig
    slider: SliderConfig
    panic: PanicConfig
    perception: PerceptionConfig
    latency: LatencyConfig
    # Loaded here so guards remain pure functions of (window, ctx, cfg) and never touch the disk.
    poses: PoseLibrary = PoseLibrary()


# --------------------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_overrides() -> dict[str, Any]:
    """GESTURE_OS_GROSS__SPEED=2.1 -> {"gross": {"speed": 2.1}}.

    Double underscore is the section separator so single-underscore key names survive.
    """
    out: dict[str, Any] = {}
    for key, raw in os.environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX) :].lower().split("__")
        if len(path) < 2:
            continue  # GESTURE_OS_OFFLINE and friends are flags, not config keys
        try:
            value: Any = float(raw) if "." in raw else int(raw)
        except ValueError:
            value = raw
        cursor = out
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value
    return out


def _modes(section: Mapping[str, Any], name: str, cast) -> dict[ModeId, Any]:
    out: dict[ModeId, Any] = {}
    for mode in ModeId:
        if mode.value not in section:
            raise ConfigError(f"[arbitration.{name}] is missing mode '{mode.value}'")
        out[mode] = cast(section[mode.value])
    return out


def _validate(cfg: Config) -> None:
    a = cfg.arbitration
    for mode in ModeId:
        if a.sustain[mode] >= a.enter[mode]:
            raise ConfigError(
                f"arbitration.sustain.{mode.value} ({a.sustain[mode]}) must be < "
                f"arbitration.enter.{mode.value} ({a.enter[mode]}). Equal or inverted thresholds "
                f"let the mode flutter at its boundary."
            )
        if a.enter_frames[mode] < 1:
            raise ConfigError(f"arbitration.enter_frames.{mode.value} must be >= 1")
        if not 0.0 < a.enter_fraction[mode] <= 1.0:
            raise ConfigError(f"arbitration.enter_fraction.{mode.value} must be in (0, 1]")
        if not 0.0 < a.sustain_fraction[mode] <= 1.0:
            raise ConfigError(
                f"arbitration.sustain_fraction.{mode.value} must be in (0, 1]"
            )
        if a.min_dwell_ms[mode] < 0 or a.refractory_ms[mode] < 0:
            raise ConfigError(f"arbitration timings for {mode.value} must be >= 0")

    for mode in ModeId:
        if a.hold_ms[mode] < 0:
            raise ConfigError(f"arbitration.hold_ms.{mode.value} must be >= 0")

    if a.window_min_frames < 2:
        raise ConfigError("window.min_frames must be >= 2 — velocity needs two samples")
    if cfg.gross.speed_sustain >= cfg.gross.speed:
        raise ConfigError("gross.speed_sustain must be < gross.speed (Schmitt pair)")
    if cfg.precision.max_palm_speed_sustain <= cfg.precision.max_palm_speed:
        raise ConfigError(
            "precision.max_palm_speed_sustain must be > max_palm_speed — staying in precision "
            "has to be easier than entering it, or the mode flutters at its boundary"
        )
    if cfg.precision.pinch_click_open <= cfg.precision.pinch_click_close:
        raise ConfigError(
            "precision.pinch.click_open must be > click_close — otherwise a held pinch chatters"
        )
    if cfg.perception.max_hands not in (1, 2):
        raise ConfigError("perception.max_hands must be 1 or 2")


def _build(raw: Mapping[str, Any]) -> Config:
    arb = raw["arbitration"]
    cfg = Config(
        arbitration=ArbitrationConfig(
            enter=_modes(arb["enter"], "enter", float),
            sustain=_modes(arb["sustain"], "sustain", float),
            enter_frames=_modes(arb["enter_frames"], "enter_frames", int),
            sustain_fraction=_modes(arb["sustain_fraction"], "sustain_fraction", float),
            enter_fraction=_modes(arb["enter_fraction"], "enter_fraction", float),
            hold_ms=_modes(arb["hold_ms"], "hold_ms", float),
            min_dwell_ms=_modes(arb["min_dwell_ms"], "min_dwell_ms", float),
            refractory_ms=_modes(arb["refractory_ms"], "refractory_ms", float),
            idle_decay_ms=float(arb["idle_decay_ms"]),
            window_span_ms=float(raw["window"]["span_ms"]),
            window_min_frames=int(raw["window"]["min_frames"]),
        ),
        gross=GrossConfig(**{k: float(v) for k, v in raw["gross"].items()}),
        precision=PrecisionConfig(
            index_extension=float(raw["precision"]["index_extension"]),
            max_palm_speed=float(raw["precision"]["max_palm_speed"]),
            max_palm_speed_sustain=float(raw["precision"]["max_palm_speed_sustain"]),
            one_euro=OneEuroConfig(
                **{k: float(v) for k, v in raw["precision"]["one_euro"].items()}
            ),
            pinch_click_close=float(raw["precision"]["pinch"]["click_close"]),
            pinch_click_open=float(raw["precision"]["pinch"]["click_open"]),
        ),
        macro=MacroConfig(**{k: float(v) for k, v in raw["macro"].items()}),
        slider=SliderConfig(
            parameter=str(raw["slider"]["parameter"]),
            pinch_max=float(raw["slider"]["pinch_max"]),
        ),
        panic=PanicConfig(
            require_both_hands=bool(raw["panic"]["require_both_hands"]),
            **{k: float(v) for k, v in raw["panic"].items() if k != "require_both_hands"},
        ),
        perception=PerceptionConfig(
            width=int(raw["perception"]["width"]),
            height=int(raw["perception"]["height"]),
            fps=int(raw["perception"]["fps"]),
            model_complexity=int(raw["perception"]["model_complexity"]),
            max_hands=int(raw["perception"]["max_hands"]),
            min_detection_confidence=float(raw["perception"]["min_detection_confidence"]),
            min_tracking_confidence=float(raw["perception"]["min_tracking_confidence"]),
            exposure=int(raw["perception"].get("exposure", 0)),
        ),
        latency=LatencyConfig(**{k: float(v) for k, v in raw["latency"].items()}),
        poses=PoseLibrary.load(),
    )
    _validate(cfg)
    return cfg


def load(
    *,
    default_path: Path = DEFAULT_CONFIG,
    profile: str | None = None,
    overrides: Mapping[str, Any] | None = None,
    use_env: bool = True,
) -> Config:
    """Load and validate. Raises ConfigError rather than returning something half-valid."""
    with default_path.open("rb") as fh:
        raw: dict[str, Any] = tomllib.load(fh)

    if profile:
        path = PROFILE_DIR / f"{profile}.toml"
        if not path.exists():
            raise ConfigError(f"profile '{profile}' not found at {path}")
        with path.open("rb") as fh:
            raw = _deep_merge(raw, tomllib.load(fh))

    if use_env:
        raw = _deep_merge(raw, _env_overrides())
    if overrides:
        raw = _deep_merge(raw, overrides)

    return _build(raw)


def offline_requested() -> bool:
    """True when the rules-only judgment provider should be used regardless of any API key."""
    return os.environ.get(f"{ENV_PREFIX}OFFLINE", "").strip() not in ("", "0", "false", "False")
