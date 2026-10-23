"""Jev point D — turn a messy recording into a macro worth keeping.

Teach-by-demonstration is only useful if the first take works. A raw AT-SPI recording of someone
doing a real task contains the misclick they corrected, the notification that stole focus, and the
menu they opened by accident — and replaying that faithfully reproduces their mistakes.

Three judgments, all at record time, none on any latency budget:

  1. **Was this step incidental?**  Per step, a Noul. Drops the noise.
  2. **Is this the same workflow as one already saved?**  A Noul per existing macro. Stops the
     library filling with near-duplicates that then compete for the same gesture.
  3. **Which pose should trigger it?**  A Choice over the user's UNBOUND poses — closed set, so an
     unbindable suggestion is impossible.

The recorder stays deliberately dumb and keeps everything (`effectors/backends/atspi_recorder.py`),
because "was that part of what you meant?" is a judgment and not a rule a recorder could apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.decision.backends.rules import register
from app.decision.judgment_config import PointConfig
from app.decision.provider import Judgment, JudgmentRequest, Source
from app.decision.questions import ChoiceQ, NoulQ, PointId
from app.types import UiAction

POINT = PointId.D_DEMO_CLEANUP

_STEP_PREFIX = "step_"


@dataclass(frozen=True, slots=True)
class CleanedMacro:
    name: str
    steps: tuple[UiAction, ...]
    dropped: tuple[UiAction, ...]
    duplicate_of: str | None
    suggested_pose: str
    confidence: float
    source: Source

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None


def _step_key(i: int) -> str:
    return f"{_STEP_PREFIX}{i}"


def build_request(
    name: str,
    actions: Sequence[UiAction],
    existing: Mapping[str, Sequence[UiAction]],
    unbound_poses: Sequence[str],
    cfg: PointConfig,
) -> JudgmentRequest:
    """One call carrying every judgment about this recording — speculative fan-out.

    All of it is rendered to text first: Jev reads "focus 'Export' in Figma", never a timestamp or
    a coordinate. Steps keep their numbering so a per-step answer maps back unambiguously.
    """
    from app.ui_actions import describe, render

    base = cfg.questions
    questions: dict[str, object] = {}

    for i, action in enumerate(actions):
        # Reference the step BY NUMBER against the full list in the state, rather than pasting the
        # step into the instruction. Judged in isolation, every step looked incidental — the noul
        # saturated at exactly 1.00 for six heterogeneous steps including the final button click,
        # which is the entire point of the workflow. Whether a step was a misclick is only
        # answerable in the context of the steps around it.
        questions[_step_key(i)] = NoulQ(
            instructions=(
                f"{base['step_incidental'].instructions}\n\n"
                f"Judge step {i + 1} of the recorded steps: \"{describe(action)}\""
            )
        )

    for macro_name, steps in existing.items():
        questions[f"dup_{macro_name}"] = NoulQ(
            instructions=(
                f"{base['is_duplicate'].instructions}\n\n"
                f"Existing workflow '{macro_name}': {render(steps)}"
            )
        )

    # Only ask when there is genuinely a choice. With one unbound pose the answer is that pose,
    # and a Choice needs two options anyway — asking would be both wasteful and invalid.
    if len(unbound_poses) > 1:  # tuning-exempt: a choice needs alternatives
        questions["pose"] = ChoiceQ(
            base["pose"].instructions,
            {p: f"The hand pose the user recorded and named '{p}'." for p in unbound_poses},
        )

    return JudgmentRequest(
        point=POINT,
        state={
            "workflow_name": name,
            "recorded_steps": render(actions),
            "step_count": len(actions),
        },
        questions=questions,
        cache_key="",  # every recording is unique; caching one would be meaningless
        rev=cfg.rev,
    )


def interpret(
    answers: Mapping[str, Judgment],
    name: str,
    actions: Sequence[UiAction],
    existing: Mapping[str, Sequence[UiAction]],
    cfg: PointConfig,
) -> CleanedMacro:
    kept: list[UiAction] = []
    dropped: list[UiAction] = []
    for i, action in enumerate(actions):
        judgment = answers.get(_step_key(i))
        incidental = bool(
            judgment
            and isinstance(judgment.value, (int, float))
            and float(judgment.value) > cfg.noul_true_threshold
        )
        (dropped if incidental else kept).append(action)

    duplicate_of = None
    for macro_name in existing:
        judgment = answers.get(f"dup_{macro_name}")
        if (
            judgment
            and isinstance(judgment.value, (int, float))
            and float(judgment.value) > cfg.noul_true_threshold
        ):
            duplicate_of = macro_name
            break

    pose_judgment = answers.get("pose")
    if pose_judgment is None and len(existing) >= 0:
        pass  # single-pose case is filled in by the caller, which knows the pose list
    source = (pose_judgment or next(iter(answers.values()), None))
    return CleanedMacro(
        name=name,
        steps=tuple(kept),
        dropped=tuple(dropped),
        duplicate_of=duplicate_of,
        suggested_pose=str(pose_judgment.value) if pose_judgment else "",
        confidence=pose_judgment.confidence if pose_judgment else 0.0,
        source=source.source if source else Source.RULES,
    )


# --------------------------------------------------------------------------------------
# Offline rules fallback
# --------------------------------------------------------------------------------------

# Applications that are almost never part of a deliberate workflow — they interrupt one.
_INTERRUPTERS = ("slack", "discord", "notification", "telegram", "thunderbird", "mail")


@register(POINT)
def fallback(req: JudgmentRequest) -> Mapping[str, Judgment]:
    """Structural cues only. It can spot an interruption; it cannot spot a misclick, which is the
    judgment this point mostly exists for. Keeping a step is the safe default — a macro with an
    extra step is annoying, a macro missing a step is broken."""
    from app.decision.judgment_config import load as _load_judgment

    fb = _load_judgment().point(POINT).fallback
    out: dict[str, Judgment] = {}

    for key, question in req.questions.items():
        instructions = getattr(question, "instructions", "").lower()
        if key.startswith(_STEP_PREFIX):
            interrupted = any(app in instructions for app in _INTERRUPTERS)
            out[key] = Judgment(
                key,
                1.0 if interrupted else 0.0,
                fb.value("interrupter_confidence") if interrupted else fb.value("keep_confidence"),
                Source.RULES,
            )
        elif key.startswith("dup_"):
            # Comparing two workflows for sameness is exactly the semantic judgment a regex
            # cannot make. Say "not a duplicate" at zero confidence rather than guess.
            out[key] = Judgment(key, 0.0, 0.0, Source.RULES)
        elif key == "pose":
            options = list(getattr(question, "options", {}) or {})
            out[key] = Judgment(
                key, options[0] if options else "", fb.value("pose_confidence"), Source.RULES
            )
    return out
