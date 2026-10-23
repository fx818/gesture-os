"""Our question vocabulary.

Domain code never imports `typesafe_sdk`; it builds these and hands them to a JudgmentProvider.
`decision/backends/typesafe.py` is the only translator. That is what makes the provider swappable
and what lets every test run with no network.

The instruction *prose* does not live here either — it lives in config/judgment/points.yaml, which
is the file the TypeSafe docs say a human must review. These classes carry it, they do not author it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Sequence


class PointId(StrEnum):
    """The seven Jev integration points, A-G. Used as a cache namespace and a config key."""

    A_APP_CONTEXT = "a_app_context"
    B_TILE_ROLE = "b_tile_role"
    C_RADIAL_RANK = "c_radial_rank"
    D_DEMO_CLEANUP = "d_demo_cleanup"
    E_NL_BINDING = "e_nl_binding"
    F_MISFIRE = "f_misfire"
    G_TEXT_SPAN = "g_text_span"


@dataclass(frozen=True, slots=True)
class ChoiceQ:
    """Pick exactly one option from a closed set.

    `options` maps an id to a description. The ids are the only things that can ever come back,
    which is why an injected instruction in the state can at worst select a wrong enum member and
    never cause an action. Descriptions help the model draw boundaries between neighbours.
    """

    instructions: str
    options: Mapping[str, str]

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError("a Choice needs at least two options")


@dataclass(frozen=True, slots=True)
class ScoreQ:
    """Position on an ordered rubric. `levels` runs low to high, 2..10 entries.

    The returned score is continuous in 0..len(levels)-1 and may land between levels.
    """

    instructions: str
    levels: Sequence[str]

    def __post_init__(self) -> None:
        if not 2 <= len(self.levels) <= 10:
            raise ValueError("a Score needs between 2 and 10 ordered levels")


@dataclass(frozen=True, slots=True)
class NoulQ:
    """Is this statement true? Returns 0..1.

    Note this primitive reports NO confidence of its own (verified against typesafe-sdk 0.6.0:
    `NoulAnswer` carries only `noul`). We derive one — see `provider.noul_confidence`.
    """

    instructions: str
    when_true: str | None = None
    when_false: str | None = None


Question = ChoiceQ | ScoreQ | NoulQ
