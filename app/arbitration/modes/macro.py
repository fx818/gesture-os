"""Macro — a held pose.

Near-zero motion sustained across the dwell window. Template matching against the pose library is
P5; this establishes the state and the dwell so the confidence HUD has something to preview and
the user has something to abort.
"""

from __future__ import annotations

from app.arbitration.guards import (
    all_of,
    for_fraction,
    openness_below,
    pose_matches,
    present,
    speed_below,
)
from app.arbitration.registry import ModeSpec
from app.types import ModeId

# Still AND holding a RECOGNISED pose.
#
# Stillness alone fires on a hand resting near the desk, which the scope doc explicitly wants
# treated as an escape hatch rather than a command — measured: a resting hand entered macro after
# 533ms. The pose requirement is what separates "deliberately holding a shape" from "not moving".
#
# `openness_below` is the fallback while the pose library is empty, and it is weak: it fires on any
# closed-ish hand. `python main.py record-pose fist` replaces it with the real thing.
_STILL = for_fraction(
    ModeId.MACRO,
    all_of(
        present(),
        speed_below("macro.max_speed"),
        pose_matches("macro.template_cosine_min", openness_below("macro.max_openness")),
    ),
)

MACRO = ModeSpec(
    mode=ModeId.MACRO,
    priority=40,  # tuning-exempt: mode ordering is structure, not tuning
    # The 450ms dwell is `arbitration.hold_ms.macro`, enforced by the engine across
    # windows. Expressing it here would cap it at the 250ms window span.
    enter=_STILL,
    sustain=_STILL,
)
