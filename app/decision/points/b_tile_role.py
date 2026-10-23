"""Jev point B — where does this window belong in the layout?

Ray-cast tiling gives the user a way to point at a snap zone. This decides which zone to
PRE-HIGHLIGHT, so pointing becomes a correction rather than a requirement — the common case
costs no aiming at all.

The confidence band matters more here than anywhere else, and in a comfortable direction: the
answer is shown as a highlight before the user commits, so a wrong suggestion costs a flick of the
finger. That is why `act_threshold` sits at 0.60 rather than point A's 0.85 — the cost of being
wrong is visible and instantly correctable, which is exactly the situation where acting on a
medium-confidence answer is right.

Composes with point A: the application class is part of the state, so "a terminal" and "a terminal
showing logs" can land differently, and the model never has to re-derive what kind of app it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from app.decision.backends.rules import register
from app.decision.judgment_config import PointConfig
from app.decision.provider import Judgment, JudgmentRequest, Source
from app.decision.questions import PointId
from app.intents import Zone
from app.naming import normalize_title
from app.types import AppClass, LayoutSnapshot, WindowInfo

POINT = PointId.B_TILE_ROLE

_ZONES = {"main": Zone.MAIN, "side_panel": Zone.SIDE_PANEL, "background": Zone.BACKGROUND}


@dataclass(frozen=True, slots=True)
class TileSuggestion:
    zone: Zone
    confidence: float
    source: Source
    provisional: bool

    @staticmethod
    def none() -> TileSuggestion:
        return TileSuggestion(Zone.MAIN, 0.0, Source.RULES, True)


def build_request(
    window: WindowInfo,
    app_class: AppClass,
    layout: LayoutSnapshot | None,
    cfg: PointConfig,
) -> JudgmentRequest:
    occupied = {"main": "empty", "side_panel": "empty", "background": "empty"}
    if layout is not None:
        # Describe what is already placed, in words. Jev cannot compare rectangles, so the
        # geometry is resolved here and only the conclusion is sent.
        for other in layout.windows:
            if other.wid == window.wid:
                continue
            slot = "main" if other.focused else "background"
            occupied[slot] = other.app_name or "another window"

    state = {
        "window_title": window.title,
        "application_name": window.app_name,
        "application_kind": app_class.value,
        "currently_in_main": occupied["main"],
        "currently_in_background": occupied["background"],
    }
    return JudgmentRequest(
        point=POINT,
        state=state,
        questions=cfg.questions,
        # The TITLE must be in the key. Keying on the application alone made
        # `ptyxis: tail -f /var/log/syslog` and `ptyxis: anurag@host: ~` share a cache entry, so
        # the second inherited "background" from the first — destroying the exact distinction this
        # point exists to make. Normalised so that a title changing as you type does not miss.
        cache_key=(
            f"{window.app_name.strip().lower()}"
            f"|{app_class.value}"
            f"|{normalize_title(window.title, app_name=window.app_name)}"
            f"|r{cfg.rev}"
        ),
        rev=cfg.rev,
    )


def interpret(answers: Mapping[str, Judgment], cfg: PointConfig) -> TileSuggestion:
    role = answers.get("zone")
    if role is None:
        return TileSuggestion.none()
    zone = _ZONES.get(str(role.value), Zone.MAIN)
    return TileSuggestion(
        zone=zone,
        confidence=role.confidence,
        source=role.source,
        provisional=role.confidence < cfg.act_threshold,
    )


# --------------------------------------------------------------------------------------
# Offline rules fallback
# --------------------------------------------------------------------------------------

# Title patterns that say what a window is FOR, independently of which application it is. A
# terminal tailing logs and a terminal you are typing in are the same app and different roles.
_BACKGROUND = re.compile(
    r"\b(log|logs|tail|htop|top|monitor|watch|journalctl|dmesg|status|dashboard)\b", re.I
)
_REFERENCE = re.compile(
    r"\b(docs?|documentation|reference|api|manual|wiki|stack overflow|mdn|man)\b", re.I
)

_BY_CLASS = {
    AppClass.CODE_EDITOR: Zone.MAIN,
    AppClass.DOCUMENT_EDITOR: Zone.MAIN,
    AppClass.TERMINAL: Zone.MAIN,
    AppClass.BROWSER: Zone.SIDE_PANEL,
    AppClass.FILE_MANAGER: Zone.SIDE_PANEL,
    AppClass.MEDIA_PLAYER: Zone.BACKGROUND,
    AppClass.PRESENTATION: Zone.MAIN,
}


@register(POINT)
def fallback(req: JudgmentRequest) -> Mapping[str, Judgment]:
    from app.decision.judgment_config import load as _load_judgment

    fb = _load_judgment().point(POINT).fallback
    title = str(req.state.get("window_title", ""))
    try:
        app_class = AppClass(str(req.state.get("application_kind", "unknown")))
    except ValueError:
        app_class = AppClass.UNKNOWN

    # Title evidence first: it describes the ROLE, which is what this question is about, whereas
    # the application class only describes what the program is.
    if _BACKGROUND.search(title):
        zone, conf = Zone.BACKGROUND, fb.value("title_confidence")
    elif _REFERENCE.search(title):
        zone, conf = Zone.SIDE_PANEL, fb.value("title_confidence")
    elif app_class in _BY_CLASS:
        zone, conf = _BY_CLASS[app_class], fb.value("class_confidence")
    else:
        zone, conf = Zone.MAIN, 0.0

    return {"zone": Judgment("zone", zone.value, conf, Source.RULES)}
