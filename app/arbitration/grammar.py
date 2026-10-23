"""Gesture grammar — short sequences of primitives that mean more than their parts.

Pure, and applied AFTER the engine emits intents rather than inside it. That ordering is
deliberate: the state machine's job is deciding what gesture just happened, and a grammar's job is
deciding what a *run* of gestures adds up to. Folding the second into the first would make every
mode aware of history, which is exactly the complexity the arbitration design avoids.

The time window is the safety mechanism. Without it, any two gestures performed minutes apart
would eventually match some rule; with it, the primitives have to arrive as a deliberate phrase.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import yaml

from app.intents import Intent

GRAMMAR_PATH = Path(__file__).resolve().parents[2] / "config" / "grammar.yaml"  # tuning-exempt: path depth


@dataclass(frozen=True, slots=True)
class GrammarRule:
    name: str
    sequence: tuple[str, ...]
    within_ms: float
    action: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class Utterance:
    """A matched phrase: which rule, and the intents it consumed."""

    rule: GrammarRule
    consumed: tuple[Intent, ...]


@dataclass(frozen=True, slots=True)
class Grammar:
    rules: tuple[GrammarRule, ...] = ()

    @property
    def max_length(self) -> int:
        return max((len(r.sequence) for r in self.rules), default=0)

    def match(self, history: Sequence[tuple[float, Intent]]) -> Utterance | None:
        """The longest rule matching the END of `history`, or None.

        Longest-first so a two-step rule cannot shadow a three-step one that extends it — the same
        reason a lexer prefers the longest token.
        """
        if not history:
            return None
        now = history[-1][0]
        for rule in sorted(self.rules, key=lambda r: -len(r.sequence)):
            n = len(rule.sequence)
            if len(history) < n:
                continue
            tail = history[-n:]
            if [i.kind for _, i in tail] != list(rule.sequence):
                continue
            if (now - tail[0][0]) > rule.within_ms:
                continue
            return Utterance(rule=rule, consumed=tuple(i for _, i in tail))
        return None


@lru_cache(maxsize=4)  # tuning-exempt: cache size
def load(path: Path = GRAMMAR_PATH) -> Grammar:
    if not Path(path).exists():
        return Grammar()
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    default_within = float((raw.get("defaults") or {}).get("within_ms", 0)) or None
    rules = []
    for spec in raw.get("rules", []):
        sequence = tuple(str(s) for s in spec.get("sequence", []))
        if len(sequence) < 2:  # tuning-exempt: a phrase needs at least two parts
            raise ValueError(
                f"grammar rule '{spec.get('name')}' has fewer than two steps; a one-step phrase "
                f"is just a gesture and would fire on every occurrence of it"
            )
        within = float(spec.get("within_ms") or default_within or 0)
        if within <= 0:
            raise ValueError(
                f"grammar rule '{spec.get('name')}' has no within_ms and no default; without a "
                f"time window any two gestures would eventually match it"
            )
        rules.append(
            GrammarRule(
                name=str(spec["name"]),
                sequence=sequence,
                within_ms=within,
                action=str(spec.get("action", "")),
                description=str(spec.get("description", "")),
            )
        )
    return Grammar(tuple(rules))
