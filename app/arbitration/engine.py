"""The arbitration engine. The core deliverable.

    step(state, window, ctx, registry, cfg) -> StepResult

PURE. No I/O, no clock, no globals, no randomness. Time arrives only on `FeatureFrame.t_ms`, so
the same inputs always produce the same output and a fixture replays bit-identically.

Resolution order, which mirrors the state diagram in docs/scope.md:

  1. PANIC, checked outside the state machine entirely
  2. any preempting mode whose guard holds across the whole window (GROSS)
  3. the incumbent, if its sustain guard still holds
  4. the best challenger that clears enter threshold, streak, dwell and refractory
  5. otherwise decay toward IDLE

Hysteresis is four independent layers, because flicker is not solved by one trick:

  1. **Schmitt thresholds** — entering needs `enter[m]`, staying only needs `sustain[m]`, and the
     loader refuses a config where sustain >= enter. A hand parked on the boundary cannot flutter.
  2. **Streak** — a challenger must win `enter_frames` consecutive windows. One good frame is not
     an intention.
  3. **Minimum dwell** — the incumbent cannot be displaced before `min_dwell_ms`, except by a
     preempting mode.
  4. **Refractory** — after leaving a mode, it cannot be re-entered for `refractory_ms`. This is
     what stops the release phase of a gesture immediately re-triggering it.
"""

from __future__ import annotations

from app.arbitration import panic
from app.arbitration.registry import ModeRegistry, ModeSpec
from app.arbitration.state import ArbiterState, ArbiterTrace, StepResult
from app.config import Config
from typing import Mapping

from app.types import DecisionContext, FeatureWindow, ModeId


def _refractory_blocked(state: ArbiterState, mode: ModeId, t_ms: float) -> bool:
    return t_ms < state.refractory_until.get(mode, 0.0)


def _update_holds(
    state: ArbiterState, scores: dict[ModeId, float], cfg: Config, t_ms: float
) -> dict[ModeId, float]:
    """Track when each mode's enter guard became continuously true.

    The hold STARTS at the enter threshold and is MAINTAINED at the lower sustain threshold —
    the Schmitt idea applied to the dwell timer. Requiring the enter threshold throughout meant a
    single noisy frame reset the whole 450ms macro dwell, and with real tracking jitter the dwell
    simply never completed. A held pose is not a demand for 14 consecutive perfect frames.

    The difference between now and that timestamp is the mode's hold, which is how a 450ms dwell
    is expressed with a 250ms feature window.
    """
    holds = dict(state.hold_since)
    for mode, score in scores.items():
        if mode in holds:
            if score < cfg.arbitration.sustain[mode]:
                holds.pop(mode, None)
        elif score >= cfg.arbitration.enter[mode]:
            holds[mode] = t_ms
    return holds


def _held_long_enough(holds: Mapping[ModeId, float], mode: ModeId, cfg: Config, t_ms: float) -> bool:
    required = cfg.arbitration.hold_ms[mode]
    if required <= 0.0:
        return True
    since = holds.get(mode)
    return since is not None and (t_ms - since) >= required


def _leave(state: ArbiterState, cfg: Config, t_ms: float) -> dict[ModeId, float]:
    refractory = dict(state.refractory_until)
    cooloff = cfg.arbitration.refractory_ms[state.mode]
    if cooloff > 0.0:
        refractory[state.mode] = t_ms + cooloff
    return refractory


def _enter(
    state: ArbiterState,
    spec: ModeSpec,
    cfg: Config,
    t_ms: float,
    confidence: float,
    window: FeatureWindow,
    ctx: DecisionContext,
    scores: dict[ModeId, float],
    holds: Mapping[ModeId, float],
    blocked_by: str = "",
) -> StepResult:
    refractory = _leave(state, cfg, t_ms)
    new_state = ArbiterState(
        mode=spec.mode,
        entered_t_ms=t_ms,
        confidence=confidence,
        candidate=None,
        candidate_streak=0,
        refractory_until=refractory,
        # The mode just entered no longer has a pending hold; everything else keeps accumulating.
        hold_since={m: v for m, v in holds.items() if m is not spec.mode},
        mode_data={},
    )
    intents = tuple(spec.handler(window, ctx, new_state, cfg, True))
    return StepResult(
        state=new_state,
        intents=intents,
        trace=ArbiterTrace(scores=scores, winner=spec.mode, blocked_by=blocked_by),
    )


def step(
    state: ArbiterState,
    window: FeatureWindow,
    ctx: DecisionContext,
    registry: ModeRegistry,
    cfg: Config,
) -> StepResult:
    t_ms = window.t_end
    arb = cfg.arbitration
    scores: dict[ModeId, float] = {}

    # Score every mode first, so hold timers are maintained for all of them — including modes we
    # will not enter this frame. A mode whose hold only started counting once it became the best
    # candidate could never accumulate a dwell while another mode was momentarily stronger.
    scores[ModeId.PANIC] = panic.check(window, ctx, cfg)
    for spec in registry.challengers():
        if spec.mode is ModeId.PANIC:
            continue
        scores[spec.mode] = spec.enter(window, ctx, cfg)

    holds = _update_holds(state, scores, cfg, t_ms)

    # (1) Panic, outside the machine.
    if (
        scores[ModeId.PANIC] >= arb.enter[ModeId.PANIC]
        and _held_long_enough(holds, ModeId.PANIC, cfg, t_ms)
        and state.mode is not ModeId.PANIC
    ):
        spec = registry.get(ModeId.PANIC)
        if spec is not None:
            return _enter(state, spec, cfg, t_ms, scores[ModeId.PANIC], window, ctx, scores, holds)

    # (1b) PANIC is sticky. While the pose is held, nothing displaces it.
    #
    # Without this, MACRO challenged and won immediately — "both hands still" satisfies macro too —
    # and the engine oscillated panic -> macro -> panic, firing ReleaseAll four times. A kill
    # switch that can be argued out of by another mode is not a kill switch. You leave PANIC by
    # releasing the pose, which drops the score below sustain and lets normal arbitration resume.
    if state.mode is ModeId.PANIC:
        if scores[ModeId.PANIC] >= arb.sustain[ModeId.PANIC]:
            spec = registry.get(ModeId.PANIC)
            held = ArbiterState(
                mode=ModeId.PANIC,
                entered_t_ms=state.entered_t_ms,
                confidence=scores[ModeId.PANIC],
                candidate=None,
                candidate_streak=0,
                refractory_until=state.refractory_until,
                hold_since=holds,
                mode_data=state.mode_data,
            )
            intents = tuple(spec.handler(window, ctx, held, cfg, False)) if spec else ()
            return StepResult(
                state=held,
                intents=intents,
                trace=ArbiterTrace(scores=scores, winner=ModeId.PANIC),
            )
        # Pose released: fall through to IDLE rather than to whatever was running before.
        idle = registry.get(ModeId.IDLE)
        if idle is not None:
            return _enter(state, idle, cfg, t_ms, 1.0, window, ctx, scores, holds, blocked_by="panic-released")

    # (2) Preemption. A mode whose guard holds across the whole window bypasses dwell and streak —
    # but "across the whole window" IS the hysteresis, so this is not a loophole.
    for spec in registry.preempting():
        if spec.mode is state.mode:
            continue
        score = scores.get(spec.mode, 0.0)
        if (
            score >= arb.enter[spec.mode]
            and _held_long_enough(holds, spec.mode, cfg, t_ms)
            and not _refractory_blocked(state, spec.mode, t_ms)
        ):
            return _enter(state, spec, cfg, t_ms, score, window, ctx, scores, holds)

    # (3) Incumbent sustains?
    incumbent = registry.get(state.mode)
    sustain_score = 0.0
    if incumbent is not None:
        sustain_score = incumbent.sustain(window, ctx, cfg)
        scores[state.mode] = max(scores.get(state.mode, 0.0), sustain_score)

    # (4) Challengers.
    best: tuple[ModeSpec, float] | None = None
    for spec in registry.challengers():
        # IDLE is the fallback state, not a competitor. Its enter guard is `always()`, so letting
        # it compete meant it scored 1.0 every frame and displaced whichever real mode was active
        # the moment min_dwell expired — 33 transitions in 4 seconds on a steady pointing gesture.
        # Idle is reached by decay (step 5) or by explicit escape, never by winning.
        if spec.mode is ModeId.IDLE:
            continue
        if spec.mode is state.mode or spec.preempt or spec.mode is ModeId.PANIC:
            continue
        score = scores.get(spec.mode, 0.0)
        if score < arb.enter[spec.mode]:
            continue
        if best is None or score > best[1]:
            best = (spec, score)

    blocked_by = ""
    if best is not None:
        spec, score = best
        dwell_ok = (t_ms - state.entered_t_ms) >= arb.min_dwell_ms[state.mode]
        refractory_ok = not _refractory_blocked(state, spec.mode, t_ms)
        hold_ok = _held_long_enough(holds, spec.mode, cfg, t_ms)

        streak = state.candidate_streak + 1 if state.candidate is spec.mode else 1
        streak_ok = streak >= arb.enter_frames[spec.mode]

        if not refractory_ok:
            blocked_by = "refractory"
        elif not dwell_ok:
            blocked_by = "dwell"
        elif not hold_ok:
            blocked_by = "hold"
        elif not streak_ok:
            blocked_by = "streak"
        else:
            return _enter(state, spec, cfg, t_ms, score, window, ctx, scores, holds)

        # Keep accumulating the streak while blocked, so the moment dwell expires the challenger
        # does not have to start counting from zero again.
        state = ArbiterState(
            mode=state.mode,
            entered_t_ms=state.entered_t_ms,
            confidence=state.confidence,
            candidate=spec.mode,
            candidate_streak=streak,
            refractory_until=state.refractory_until,
            hold_since=holds,
            mode_data=state.mode_data,
        )
    else:
        state = ArbiterState(
            mode=state.mode,
            entered_t_ms=state.entered_t_ms,
            confidence=state.confidence,
            candidate=None,
            candidate_streak=0,
            refractory_until=state.refractory_until,
            hold_since=holds,
            mode_data=state.mode_data,
        )

    # (5) Incumbent holds, or decays to Idle.
    if incumbent is not None and sustain_score >= arb.sustain[state.mode]:
        intents = tuple(incumbent.handler(window, ctx, state, cfg, False))
        held = ArbiterState(
            mode=state.mode,
            entered_t_ms=state.entered_t_ms,
            confidence=sustain_score,
            candidate=state.candidate,
            candidate_streak=state.candidate_streak,
            refractory_until=state.refractory_until,
            hold_since=holds,
            mode_data=state.mode_data,
        )
        return StepResult(
            state=held,
            intents=intents,
            trace=ArbiterTrace(scores=scores, winner=state.mode, blocked_by=blocked_by),
        )

    if state.mode is not ModeId.IDLE and (t_ms - state.entered_t_ms) >= arb.idle_decay_ms:
        # The coffee-cup escape hatch: motion that never resolves into a committed pattern decays
        # back to Idle instead of being force-fit into whatever mode was last active.
        idle = registry.get(ModeId.IDLE)
        if idle is not None:
            return _enter(state, idle, cfg, t_ms, 1.0, window, ctx, scores, holds, blocked_by="decay")

    return StepResult(
        state=state,
        intents=(),
        trace=ArbiterTrace(scores=scores, winner=state.mode, blocked_by=blocked_by),
    )
