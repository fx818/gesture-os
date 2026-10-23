"""Jev point E — bind a gesture by describing it.

    "tile this left when I'm coding"  ->  Binding(trigger=swipe_left, context=code_editor,
                                                  action=tile_left)

This is the docs' `function_calling` pattern, and it is the cleanest demonstration of why Jev is
the right shape of tool for this project. Every argument is a **closed set** we define:

  * action  — an id from `config/actions.yaml`
  * context — an `AppClass`, or `any`
  * trigger — a gesture the engine can actually detect, or a pose the user has recorded

Jev never generates a value; it picks one from each set. So an invalid binding is not merely
unlikely, it is **structurally impossible** — there is no string the model could emit that would
produce a binding the system cannot execute. That property is what makes it safe to accept
free-text input from a person (or from dictation) at all.

Config time only: no latency budget, no realtime path, and a wrong answer is visible and
rejectable before anything is saved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.actions import ANY, ActionCatalogue
from app.decision.backends.rules import register
from app.decision.judgment_config import PointConfig
from app.decision.provider import Judgment, JudgmentRequest, Source
from app.decision.questions import ChoiceQ, PointId
from app.types import AppClass

POINT = PointId.E_NL_BINDING

# Triggers the arbitration engine can actually detect today. Poses the user has recorded are added
# at request time. Nothing outside this list can be bound, because nothing outside it can fire.
BUILTIN_TRIGGERS: dict[str, str] = {
    "swipe_left": "Sweeping the hand quickly to the left.",
    "swipe_right": "Sweeping the hand quickly to the right.",
    "pinch": "Touching thumb and index finger together while pointing.",
}

_CONTEXT_DESCRIPTIONS = {
    AppClass.CODE_EDITOR: "While writing or editing code.",
    AppClass.BROWSER: "While using a web browser.",
    AppClass.TERMINAL: "While working in a terminal or command line.",
    AppClass.PRESENTATION: "While presenting or editing slides.",
    AppClass.MEDIA_PLAYER: "While watching video or listening to music.",
    AppClass.FILE_MANAGER: "While browsing files and folders.",
    AppClass.DOCUMENT_EDITOR: "While writing prose, notes or a spreadsheet.",
}


@dataclass(frozen=True, slots=True)
class Binding:
    trigger: str
    context: str
    action: str
    confidence: float
    source: Source

    @property
    def valid(self) -> bool:
        return bool(self.trigger and self.action)

    def describe(self, catalogue: ActionCatalogue) -> str:
        spec = catalogue.get(self.action)
        where = "anywhere" if self.context == ANY else f"in a {self.context.replace('_', ' ')}"
        return f"{self.trigger.replace('_', ' ')} -> {spec.label if spec else self.action} ({where})"


def build_questions(
    catalogue: ActionCatalogue, poses: Sequence[str], cfg: PointConfig
) -> dict[str, ChoiceQ]:
    """Questions are assembled at REQUEST time, not read from points.yaml.

    The option sets depend on what exists right now — which actions the catalogue defines, which
    poses this user has recorded — so they cannot be static text. The *instructions* still come
    from points.yaml; only the closed sets are computed.
    """
    triggers = dict(BUILTIN_TRIGGERS)
    for pose in poses:
        triggers[f"pose:{pose}"] = f"Holding the '{pose}' hand pose still."

    contexts = {ANY: "In any application; the binding always applies."}
    contexts.update({c.value: d for c, d in _CONTEXT_DESCRIPTIONS.items()})

    base = cfg.questions
    return {
        # Every action, not just the context-free ones: the context is its own question, and
        # filtering here would make 'next slide' impossible to bind at all.
        "action": ChoiceQ(base["action"].instructions, catalogue.options(app_class=None)),
        "context": ChoiceQ(base["context"].instructions, contexts),
        "trigger": ChoiceQ(base["trigger"].instructions, triggers),
    }


def build_request(
    phrase: str, catalogue: ActionCatalogue, poses: Sequence[str], cfg: PointConfig
) -> JudgmentRequest:
    return JudgmentRequest(
        point=POINT,
        # The phrase is the user's own words, but it is still untrusted state — dictation output,
        # or something pasted. It goes in a labelled field and every answer is a closed set.
        state={"request": phrase, "available_poses": ", ".join(poses) or "none recorded yet"},
        questions=build_questions(catalogue, poses, cfg),
        cache_key="",  # each phrase is a one-off; caching a binding request would be pointless
        rev=cfg.rev,
    )


def interpret(answers: Mapping[str, Judgment], cfg: PointConfig) -> Binding:
    def pick(key: str) -> tuple[str, float, Source]:
        j = answers.get(key)
        return (str(j.value), j.confidence, j.source) if j else ("", 0.0, Source.RULES)

    action, ac, source = pick("action")
    context, cc, _ = pick("context")
    trigger, tc, _ = pick("trigger")
    return Binding(
        trigger=trigger,
        context=context or ANY,
        action=action,
        # The WEAKEST argument decides. A binding is only as trustworthy as its least certain
        # part: being sure about the action while guessing the trigger produces a confident-looking
        # binding that fires on the wrong gesture.
        confidence=min(ac, cc, tc),
        source=source,
    )


# --------------------------------------------------------------------------------------
# Offline rules fallback — keyword matching, and honest about being crude
# --------------------------------------------------------------------------------------


@register(POINT)
def fallback(req: JudgmentRequest) -> Mapping[str, Judgment]:
    from app.decision.judgment_config import load as _load_judgment

    fb = _load_judgment().point(POINT).fallback
    phrase = str(req.state.get("request", "")).lower()

    def best(key: str) -> tuple[str, float]:
        question = req.questions.get(key)
        if question is None:
            return "", 0.0
        # Score each option by how many of its id's words appear in the phrase. Crude on purpose:
        # this exists so `--offline` still does something, not to rival the model.
        scored = []
        for option in question.options:
            words = [w for w in option.replace(":", " ").split("_") if len(w) > 2]  # tuning-exempt: skips "to"/"of"-style noise
            hits = sum(1 for w in words if w in phrase)
            scored.append((hits, option))
        scored.sort(key=lambda kv: -kv[0])
        top_hits, top = scored[0]
        return (top, fb.value("keyword_confidence")) if top_hits else ("", 0.0)

    out: dict[str, Judgment] = {}
    for key in ("action", "context", "trigger"):
        value, conf = best(key)
        out[key] = Judgment(key, value, conf, Source.RULES)
    if not out["context"].value:
        out["context"] = Judgment("context", ANY, fb.value("default_context_confidence"), Source.RULES)
    return out
