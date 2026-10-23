"""Jev point F — misfire post-mortem.

The second Jev integration, and the safest one to build: strictly offline, batched overnight, no
latency budget and no rate-limit pressure. It is also the one that feeds back into the thresholds
everything else depends on.

Every panic gesture is a labelled negative example that only a human could have produced — the
user physically asserted "that was wrong". This turns a pile of those into a cause distribution
you can act on, instead of a folder nobody reads.

What Jev is asked is deliberately narrow. The episode has already been rendered into plain language
by `telemetry/ring.py`, because Jev cannot count or compare numbers; the questions here are a
truth judgment and a closed-set pick, which are exactly its documented strengths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from app.decision.backends.rules import register
from app.decision.judgment_config import PointConfig
from app.decision.provider import Judgment, JudgmentRequest, Source
from app.decision.questions import PointId

POINT = PointId.F_MISFIRE


@dataclass(frozen=True, slots=True)
class Verdict:
    unintended: bool
    confidence: float
    cause: str
    cause_confidence: float
    source: Source

    @property
    def actionable(self) -> bool:
        return self.unintended and self.cause != "unclear"


def build_request(state: Mapping[str, str], cfg: PointConfig, key: str) -> JudgmentRequest:
    return JudgmentRequest(
        point=POINT, state=dict(state), questions=cfg.questions, cache_key=key, rev=cfg.rev
    )


def interpret(answers: Mapping[str, Judgment], cfg: PointConfig) -> Verdict:
    unintended = answers.get("was_unintended")
    cause = answers.get("cause")
    fired = bool(
        unintended
        and isinstance(unintended.value, (int, float))
        and float(unintended.value) > cfg.noul_true_threshold
    )
    return Verdict(
        unintended=fired,
        confidence=unintended.confidence if unintended else 0.0,
        cause=str(cause.value) if cause else "unclear",
        cause_confidence=cause.confidence if cause else 0.0,
        source=(cause or unintended).source if (cause or unintended) else Source.RULES,
    )


# --------------------------------------------------------------------------------------
# Offline rules fallback
# --------------------------------------------------------------------------------------

# Deliberately crude. The point of the fallback is that the nightly batch still produces SOMETHING
# when Jev is unreachable, so misfires do not silently pile up unanalysed — not that it competes
# with the model on nuance.
_ACTED = re.compile(
    r"\b(SendToWorkspace|SwitchWindow|SendToMonitor|ShowDesktop|TileWindow|RunMacro|ButtonPress)\b"
)


@register(POINT)
def fallback(req: JudgmentRequest) -> Mapping[str, Judgment]:
    from app.decision.judgment_config import load as _load_judgment

    fb = _load_judgment().point(POINT).fallback
    actions = str(req.state.get("actions_the_system_took", ""))
    movement = str(req.state.get("hand_movement", ""))
    direction = str(req.state.get("hand_direction", ""))
    near = str(req.state.get("modes_that_nearly_activated", ""))

    acted = bool(_ACTED.search(actions))
    # A panic gesture after the system acted is very likely a real misfire; after it did nothing,
    # the user was most likely just disengaging.
    if acted:
        unintended = fb.value("unintended_after_action")
        confidence = fb.value("unintended_after_action_confidence")
    else:
        unintended = fb.value("unintended_no_action")
        confidence = fb.value("unintended_no_action_confidence")

    # `unclear` rather than a guess: a wrong cause pollutes the very distribution the thresholds
    # are meant to be tuned from.
    cause, cause_conf = "unclear", 0.0
    if acted:
        if "erratically" in direction:
            cause, cause_conf = "threshold_too_low", fb.value("cause_erratic_confidence")
        elif near and near != "none":
            cause, cause_conf = "pose_ambiguity", fb.value("cause_ambiguity_confidence")
        elif "slowly" in movement or "stationary" in movement:
            cause, cause_conf = "threshold_too_low", fb.value("cause_slow_confidence")

    return {
        "was_unintended": Judgment("was_unintended", unintended, confidence, Source.RULES),
        "cause": Judgment("cause", cause, cause_conf, Source.RULES),
    }
