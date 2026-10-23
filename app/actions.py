"""The action catalogue: what a gesture can be bound to.

Deliberately split from the id->Intent mapping, which lives in `routing/actions.py`. This half is
pure data — ids, human descriptions, which contexts an action is offered in — so it can sit at the
bottom of the stack where BOTH `decision` (which asks Jev to pick from it) and `routing` (which
executes it) can read it without either importing the other.

The closed set is the whole safety argument for Jev points C and E: the model picks an id from
this file and never produces one, so a misread instruction yields the wrong action, never an
arbitrary one.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

import yaml

CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "config" / "actions.yaml"
ANY = "any"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    id: str
    label: str
    description: str
    contexts: tuple[str, ...] = (ANY,)

    def available_in(self, app_class: str) -> bool:
        return ANY in self.contexts or app_class in self.contexts


@dataclass(frozen=True, slots=True)
class ActionCatalogue:
    actions: Mapping[str, ActionSpec]

    def get(self, action_id: str) -> ActionSpec | None:
        return self.actions.get(action_id)

    def for_context(self, app_class: str) -> tuple[ActionSpec, ...]:
        """Only the actions that make sense where the user is.

        Narrowing before asking matters for both cost and accuracy: offering 'next slide' while
        someone is in a terminal invites a wrong answer that a filter makes impossible.
        """
        return tuple(a for a in self.actions.values() if a.available_in(app_class))

    def options(self, app_class: str | None = None) -> dict[str, str]:
        """Shape Jev's Choice expects: {id: description}.

        `app_class=None` offers EVERY action. That is what binding (point E) wants: the user is
        choosing what a gesture should do, and the context is a separate question — filtering here
        would silently make context-specific actions like 'next slide' unbindable. Pass an
        app_class only when narrowing to what is usable *right now*, as the radial menu does.
        """
        source = self.actions.values() if app_class is None else self.for_context(app_class)
        return {a.id: a.description for a in source}

    def __len__(self) -> int:
        return len(self.actions)


@lru_cache(maxsize=4)  # tuning-exempt: cache size
def load(path: Path = CATALOGUE_PATH) -> ActionCatalogue:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    actions: dict[str, ActionSpec] = {}
    for action_id, spec in (raw.get("actions") or {}).items():
        spec = spec or {}
        description = " ".join(str(spec.get("description", "")).split())
        if not description:
            raise ValueError(f"action '{action_id}' has no description; Jev would see a blank option")
        actions[action_id] = ActionSpec(
            id=str(action_id),
            label=str(spec.get("label", action_id)),
            description=description,
            contexts=tuple(str(c) for c in (spec.get("contexts") or [ANY])),
        )
    if len(actions) < 2:
        raise ValueError("the action catalogue needs at least two actions to form a Choice")
    return ActionCatalogue(actions=actions)
