"""Mode registry.

Adding a gesture mode is one file in `modes/` plus one line in `modes/__init__.py`. `engine.py`
never changes. The registry is passed INTO `step()` as an argument, so a test can build a
two-mode registry and exercise the state machine in isolation with no global mutation and no
monkeypatching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

from app.arbitration.guards import Guard
from app.arbitration.state import ArbiterState
from app.config import Config
from app.intents import Intent
from app.types import DecisionContext, FeatureWindow, ModeId

# `entered` distinguishes the frame a mode was entered on from the frames it is merely sustaining.
# Without it a discrete gesture emits its command on every sustained frame: a single swipe produced
# 18 SendToWorkspace intents, i.e. 18 workspace switches.
ModeHandler = Callable[
    [FeatureWindow, DecisionContext, ArbiterState, Config, bool], Sequence[Intent]
]


def no_intents(w: FeatureWindow, ctx: DecisionContext, st: ArbiterState, cfg: Config, entered: bool):
    return ()


@dataclass(frozen=True, slots=True)
class ModeSpec:
    mode: ModeId
    priority: int
    enter: Guard
    sustain: Guard
    handler: ModeHandler = no_intents
    preempt: bool = False
    required_caps: frozenset[str] = frozenset()


class DuplicateMode(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModeRegistry:
    specs: Mapping[ModeId, ModeSpec] = field(default_factory=dict)

    @classmethod
    def build(cls, specs: Iterable[ModeSpec]) -> ModeRegistry:
        out: dict[ModeId, ModeSpec] = {}
        priorities: dict[int, ModeId] = {}
        for spec in specs:
            if spec.mode in out:
                raise DuplicateMode(f"mode {spec.mode.value} registered twice")
            if spec.priority in priorities:
                raise DuplicateMode(
                    f"modes {priorities[spec.priority].value} and {spec.mode.value} share "
                    f"priority {spec.priority}; ordering would be non-deterministic"
                )
            priorities[spec.priority] = spec.mode
            out[spec.mode] = spec
        return cls(specs=out)

    def get(self, mode: ModeId) -> ModeSpec | None:
        return self.specs.get(mode)

    def challengers(self) -> tuple[ModeSpec, ...]:
        """Every mode, highest priority first. Ordering is total and deterministic because
        duplicate priorities are refused at build time."""
        return tuple(sorted(self.specs.values(), key=lambda s: -s.priority))

    def preempting(self) -> tuple[ModeSpec, ...]:
        return tuple(s for s in self.challengers() if s.preempt)
