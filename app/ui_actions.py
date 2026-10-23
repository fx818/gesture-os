"""Rendering recorded UI actions to the text Jev reads.

Pure functions over `UiAction`, kept below both `decision` and `effectors` because those are
sibling layers: the recorder produces these, point D consumes them, and neither may import the
other.

The rendering is the interesting part. Jev point D is asked "was this step incidental?", and the
only thing it ever sees is a sentence like `focus 'Export' in Figma` — never a timestamp, never a
widget id, never a coordinate. Turning the event into prose here is what makes the question
answerable by a text-only model.
"""

from __future__ import annotations

from typing import Sequence

from app.types import UiAction


def describe(action: UiAction) -> str:
    """One recorded step, in the words Jev will read."""
    target = f"'{action.target_name}'" if action.target_name else f"a {action.target_role}"
    return f"{action.verb} {target} in {action.app_name}"


def render(actions: Sequence[UiAction]) -> str:
    """A whole recording, numbered so a per-step answer maps back unambiguously."""
    return "; ".join(f"{i + 1}. {describe(a)}" for i, a in enumerate(actions))
