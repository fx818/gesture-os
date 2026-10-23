"""Panic as a registered mode, so the engine has somewhere to transition TO.

The detection lives in `arbitration/panic.py` and runs before any transition logic. This spec
exists so the state machine can represent being in PANIC; its enter guard is `never()` because
nothing reaches it through the normal challenger path.
"""

from __future__ import annotations

from app.arbitration.guards import always, never
from app.arbitration.registry import ModeSpec
from app.intents import ReleaseAll
from app.types import ModeId


def _handler(w, ctx, st, cfg, entered: bool):
    return (ReleaseAll(),) if entered else ()


PANIC = ModeSpec(
    mode=ModeId.PANIC,
    priority=99,  # tuning-exempt: mode ordering is structure, not tuning
    enter=never(),
    sustain=always(),
    handler=_handler,
)
