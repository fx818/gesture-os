"""Jev point A — what kind of application has focus?

The first integration point, and deliberately so: its input (app name + window title from AT-SPI)
already exists on this machine with no camera and no installs, so it validates the entire decision
stack — key, SDK, latency, calibration, caching, offline fallback — before anything depends on it.

Feeds app-aware gesture remapping and bimanual chord contexts (both V3), and Jev point B.

The rules fallback lives in this file on purpose. Prompt and fallback are reviewed together, so the
fallback cannot silently rot while the prompt evolves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping

from app.naming import cache_key
from app.decision.backends.rules import register
from app.decision.judgment_config import FallbackRule, PointConfig
from app.decision.provider import Judgment, JudgmentRequest, Source
from app.decision.questions import PointId
from app.types import AppClass, FocusInfo

POINT = PointId.A_APP_CONTEXT


@dataclass(frozen=True, slots=True)
class AppContext:
    app_class: AppClass
    confidence: float
    source: Source
    provisional: bool  # 0.5-0.9: usable, but flagged on the HUD
    text_entry: bool
    fullscreen_media: bool
    probabilities: Mapping[str, float] | None = None

    @staticmethod
    def unknown() -> AppContext:
        return AppContext(
            app_class=AppClass.UNKNOWN,
            confidence=0.0,
            source=Source.RULES,
            provisional=True,
            text_entry=False,
            fullscreen_media=False,
        )


def build_request(focus: FocusInfo, cfg: PointConfig) -> JudgmentRequest:
    """State is data only. The title is scrubbed and truncated by the provider before it leaves."""
    return JudgmentRequest(
        point=POINT,
        state={
            "application_name": focus.app_name,
            "window_title": focus.window_title,
            "window_role": focus.role,
        },
        questions=cfg.questions,
        cache_key=cache_key(focus, rev=cfg.rev),
        rev=cfg.rev,
    )


def interpret(answers: Mapping[str, Judgment], cfg: PointConfig) -> AppContext:
    cls = answers.get("app_class")
    if cls is None:
        return AppContext.unknown()
    try:
        app_class = AppClass(str(cls.value))
    except ValueError:
        # A value outside the closed set should be impossible, but if the API ever returns one,
        # treating it as unknown is the only safe reading — never pass it through to a gesture map.
        app_class = AppClass.UNKNOWN

    def truthy(key: str) -> bool:
        j = answers.get(key)
        return bool(
            j
            and isinstance(j.value, (int, float))
            and float(j.value) > cfg.noul_true_threshold
        )

    return AppContext(
        app_class=app_class,
        confidence=cls.confidence,
        source=cls.source,
        provisional=cls.confidence < cfg.act_threshold,
        text_entry=truthy("is_text_entry"),
        fullscreen_media=truthy("is_fullscreen_media"),
        probabilities=cls.probabilities,
    )


# --------------------------------------------------------------------------------------
# Offline rules fallback
# --------------------------------------------------------------------------------------

# The rules table itself now lives in config/judgment/points.yaml, under this point's
# `fallback:` block — beside the prompt it backs up, and reachable by calibration. What remains
# here is only the matching STRATEGY, which is a design decision rather than a tuning constant:
#
#   application name first, at full confidence; then the window title, discounted.
#
# Matching one combined haystack instead produced confidently-wrong answers (`alacritty` running
# `nvim` -> code_editor at 0.80), which is worse than `unknown` because 0.80 clears most act
# thresholds. See docs/verification/p1-calibration.md.

_NON_WORD = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=32)  # tuning-exempt: cache size, not a threshold
def _compiled(rules: tuple[FallbackRule, ...]) -> tuple[tuple[re.Pattern[str], AppClass, float], ...]:
    out = []
    for rule in rules:
        try:
            app_class = AppClass(rule.app_class)
        except ValueError:
            continue  # an unknown class in config must not crash the offline path
        out.append((re.compile(rf"\b({rule.pattern})\b"), app_class, rule.confidence))
    return tuple(out)


def _normalise(text: str) -> str:
    """Lowercase and split on punctuation, so `sublime_text`, `code-oss` and
    `org.gnome.TextEditor` all match the word-boundary patterns they obviously should."""
    return _NON_WORD.sub(" ", text.lower()).strip()


def _match(haystack: str, rules) -> tuple[AppClass, float]:
    for pattern, cls, conf in _compiled(rules):
        if pattern.search(haystack):
            return cls, conf
    return AppClass.UNKNOWN, 0.0


_TEXT_ENTRY_CLASSES = frozenset(
    {AppClass.CODE_EDITOR, AppClass.TERMINAL, AppClass.DOCUMENT_EDITOR}
)


@register(POINT)
def fallback(req: JudgmentRequest) -> Mapping[str, Judgment]:
    from app.decision.judgment_config import load as _load_judgment

    fb = _load_judgment().point(POINT).fallback
    rules = fb.rules
    app_name = _normalise(str(req.state.get("application_name", "")))
    title = _normalise(str(req.state.get("window_title", "")))

    # Application name first, at full confidence.
    app_class, confidence = _match(app_name, rules)
    if app_class is AppClass.UNKNOWN:
        # Then the title, discounted — it is genuinely weaker evidence.
        app_class, base = _match(title, rules)
        confidence = round(base * fb.title_confidence_factor, 3)  # tuning-exempt: rounding precision
    elif confidence < fb.ambiguous_confidence_max:
        # A low-confidence app-name match (libreoffice/soffice) says nothing about which
        # component is open. Let the title pick between Writer / Calc / Impress.
        refined, base = _match(title, rules)
        if refined is not AppClass.UNKNOWN:
            app_class, confidence = refined, round(base * fb.title_refine_factor, 3)  # tuning-exempt: rounding precision

    out: dict[str, Judgment] = {
        "app_class": Judgment(
            key="app_class", value=app_class.value, confidence=confidence, source=Source.RULES
        )
    }
    if "is_text_entry" in req.questions:
        out["is_text_entry"] = Judgment(
            key="is_text_entry",
            value=1.0 if app_class in _TEXT_ENTRY_CLASSES else 0.0,
            # Only as confident as the class it is derived from, never more.
            confidence=confidence,
            source=Source.RULES,
        )
    if "is_fullscreen_media" in req.questions:
        out["is_fullscreen_media"] = Judgment(
            key="is_fullscreen_media",
            value=1.0 if app_class is AppClass.MEDIA_PLAYER else 0.0,
            confidence=confidence,
            source=Source.RULES,
        )
    return out
