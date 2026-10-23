"""One Euro filter, written as a pure fold rather than a stateful object.

`one_euro_step(state, x, t_ms, cfg) -> (state, value)` means replaying a fixture produces
bit-identical floats every time, which is what makes golden intent streams reproducible. An object
holding mutable state would make replay depend on construction order and on whether anything else
had touched the instance.

Reference: Casiez, Roussel & Vogel, "1€ Filter" (CHI 2012). The adaptive cutoff is the whole point:
low cutoff when still (kills jitter), high cutoff when moving fast (kills lag). A fixed low-pass
has to choose one, and either the cursor shakes at rest or it drags behind the hand.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.config import OneEuroConfig

# tuning-exempt: 2*pi is the definition of angular frequency, not a threshold
_TWO_PI = 2.0 * math.pi


@dataclass(frozen=True, slots=True)
class OneEuroState:
    x_hat: float | None = None
    dx_hat: float = 0.0
    t_ms: float | None = None


def _alpha(cutoff: float, dt_s: float) -> float:
    tau = 1.0 / (_TWO_PI * cutoff)
    return 1.0 / (1.0 + tau / dt_s)


def one_euro_step(
    state: OneEuroState, x: float, t_ms: float, cfg: OneEuroConfig
) -> tuple[OneEuroState, float]:
    if state.x_hat is None or state.t_ms is None:
        return OneEuroState(x_hat=x, dx_hat=0.0, t_ms=t_ms), x

    dt_s = (t_ms - state.t_ms) / 1000.0
    if dt_s <= 0.0:
        # Duplicate or out-of-order timestamp. Returning the previous estimate unchanged is the
        # only safe response; dividing by it would produce an infinite derivative and a cursor
        # that teleports.
        return state, state.x_hat

    dx = (x - state.x_hat) / dt_s
    dx_hat = state.dx_hat + _alpha(cfg.d_cutoff, dt_s) * (dx - state.dx_hat)
    cutoff = cfg.min_cutoff + cfg.beta * abs(dx_hat)
    x_hat = state.x_hat + _alpha(cutoff, dt_s) * (x - state.x_hat)
    return OneEuroState(x_hat=x_hat, dx_hat=dx_hat, t_ms=t_ms), x_hat


@dataclass(frozen=True, slots=True)
class OneEuroVec2State:
    x: OneEuroState = OneEuroState()
    y: OneEuroState = OneEuroState()


def one_euro_step_vec2(
    state: OneEuroVec2State, x: float, y: float, t_ms: float, cfg: OneEuroConfig
) -> tuple[OneEuroVec2State, tuple[float, float]]:
    sx, vx = one_euro_step(state.x, x, t_ms, cfg)
    sy, vy = one_euro_step(state.y, y, t_ms, cfg)
    return OneEuroVec2State(sx, sy), (vx, vy)
