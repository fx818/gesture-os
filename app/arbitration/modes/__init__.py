"""Registered modes.

Adding a gesture mode is one file here plus one line below. `engine.py` never changes.
"""

from app.arbitration.modes.gross import GROSS
from app.arbitration.modes.idle import IDLE
from app.arbitration.modes.macro import MACRO
from app.arbitration.modes.panic_mode import PANIC
from app.arbitration.modes.precision import PRECISION
from app.arbitration.modes.slider import SLIDER
from app.arbitration.registry import ModeRegistry

ALL_MODES = (IDLE, PRECISION, MACRO, GROSS, SLIDER, PANIC)


def default_registry() -> ModeRegistry:
    return ModeRegistry.build(ALL_MODES)
