"""The frame pipeline: source -> features -> window -> arbiter -> intents -> router -> effectors.

Deliberately a plain function over an iterator of frames, with no clock of its own. That is what
lets `replay` run a fixture through the exact same code the live loop uses, and what makes golden
intent streams a faithful record rather than an approximation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.arbitration.engine import step
from app.arbitration.grammar import Grammar, load as load_grammar
from app.arbitration.modes import default_registry
from app.arbitration.registry import ModeRegistry
from app.arbitration.state import ArbiterState
from app.config import Config, load as load_config
from app.effectors.ports import EffectorSet
from app.features.extract import ExtractState, extract
from app.features.window import WindowBuffer
from app.intents import Intent
from app.perception.source import LandmarkSource
from app.routing.journal import ActionJournal
from app.routing.router import IntentRouter, RouteReport
from app.runtime.watchdog import PanicWatchdog
from app.telemetry.ring import EventRing, dump
from app.types import DecisionContext, HudState, ModeId


@dataclass
class EmittedIntent:
    t_ms: float
    mode: ModeId
    intent: Intent
    confidence: float


@dataclass
class PipelineResult:
    frames: int = 0
    span_ms: float = 0.0
    intents: list[EmittedIntent] = field(default_factory=list)
    transitions: list[tuple[float, ModeId]] = field(default_factory=list)
    utterances: list[str] = field(default_factory=list)
    report: RouteReport = field(default_factory=RouteReport)
    watchdog_fires: int = 0
    misfire_dumps: list = field(default_factory=list)

    @property
    def unsupported(self) -> list[str]:
        return self.report.unsupported


def run_pipeline(
    source: LandmarkSource,
    effectors: EffectorSet,
    *,
    cfg: Config | None = None,
    ctx: DecisionContext | None = None,
    registry: ModeRegistry | None = None,
    dump_intents: bool = False,
    dispatch: bool = True,
    watchdog: bool = True,
    record_misfires: bool = False,
    hud=None,
    context_service=None,
) -> PipelineResult:
    cfg = cfg or load_config()
    registry = registry or default_registry()
    caps = frozenset(effectors.capabilities())
    static_ctx = ctx or DecisionContext.empty()

    def current_context(t_ms: float, window=None) -> DecisionContext:
        """The engine's view of the outside world for this frame.

        Never blocks and never calls Jev — `snapshot()` reads whatever the broker has already
        delivered. Capabilities are injected here because they are a property of how the system
        was wired, not of what Jev knows.
        """
        base = context_service.snapshot(t_ms) if context_service is not None else static_ctx
        # The chord is derived from the CURRENT window, not from the context service: it is a
        # property of what the off-hand is doing right now, and it must not lag by a round trip.
        chord = None
        if window is not None:
            from app.arbitration.chording import detect

            held = detect(window, cfg)
            chord = held.pose if held.active else None
        return DecisionContext(
            focus=base.focus,
            app_class=base.app_class,
            app_class_confidence=base.app_class_confidence,
            app_class_age_ms=base.app_class_age_ms,
            active_chord=chord,
            recent_actions=base.recent_actions,
            capabilities=caps,
        )

    router = IntentRouter(effectors)
    journal = ActionJournal()
    grammar = load_grammar()
    history: list[tuple[float, Intent]] = []
    guard = PanicWatchdog(effectors, cfg.panic) if watchdog else None
    ring = EventRing()
    result = PipelineResult()
    extract_state = ExtractState()
    buffer = WindowBuffer(
        span_ms=cfg.arbitration.window_span_ms, min_frames=cfg.arbitration.window_min_frames
    )
    state = ArbiterState()

    first_t: float | None = None
    last_t = 0.0

    for frame in source.frames():
        if first_t is None:
            first_t = frame.t_ms
        last_t = frame.t_ms
        result.frames += 1

        # Apply anything the judgment thread finished since the last frame. Non-blocking by
        # construction — this is the only point where Jev's answers enter the loop.
        if context_service is not None:
            context_service.drain()

        extract_state, features = extract(extract_state, frame, cfg.precision)

        # The watchdog sees every feature frame, BEFORE the window has even formed and regardless
        # of what the engine is doing. That independence is the whole point (scope doc: the panic
        # gesture must work "even mid-macro or mid-drag").
        if guard is not None and guard.observe(features):
            result.watchdog_fires += 1
            # A panic gesture is a labelled negative the user physically asserted. Capture the
            # preceding two seconds while they still exist — this is Jev point F's entire input.
            if record_misfires:
                result.misfire_dumps.append(dump(ring.window(features.t_ms), cfg))

        buffer, window = buffer.push(features)
        if window is None:
            continue

        ctx = current_context(window.t_end, window)
        outcome = step(state, window, ctx, registry, cfg)
        ring.push(window.t_end, outcome.state.mode, features, outcome.trace, outcome.intents)
        if outcome.state.mode is not state.mode:
            result.transitions.append((window.t_end, outcome.state.mode))
        state = outcome.state

        # A mode that activates and emits nothing is the failure mode this project keeps calling
        # the worst kind: it looks like it worked. Surface it rather than leaving the user to
        # guess (see the note in arbitration/modes/gross.py).
        entered_silently = (
            outcome.state.mode is not state.mode and not outcome.intents
        )

        if hud is not None:
            # Dwell progress is what makes the macro abortable: the scope doc wants the user to
            # see WHAT is about to fire while there is still time to open their hands.
            hold_since = outcome.state.hold_since.get(ModeId.MACRO)
            required = cfg.arbitration.hold_ms[ModeId.MACRO]
            progress = 0.0
            preview = None
            if hold_since is not None and required > 0 and outcome.state.mode is not ModeId.MACRO:
                progress = min(1.0, (window.t_end - hold_since) / required)
                h = features.right or features.left
                if h is not None and not cfg.poses.is_empty:
                    preview = cfg.poses.best(h.joint_angles).name or None
                # The radial menu appears during the dwell — the same window in which the user
                # can still abort. Wedges come from point C's PREFETCHED ranking, so this is a
                # cache read and cannot make the menu late (ADR-0004).
                if context_service is not None and effectors.overlay is not None:
                    wedges = context_service.wedges()
                    if wedges:
                        try:
                            effectors.overlay.show_radial(wedges, None)
                        except Exception:  # noqa: BLE001
                            pass
            try:
                hud.show_hud(
                    HudState(
                        hands=sum(
                            1 for h in (features.left, features.right) if h is not None
                        ),
                        palm_speed=max(
                            (h.palm_speed for h in (features.left, features.right) if h),
                            default=0.0,
                        ),
                        mode=outcome.state.mode,
                        mode_confidence=outcome.state.confidence,
                        app_class=ctx.app_class.value,
                        dwell_progress=progress,
                        dwell_preview=preview,
                        degraded=tuple(sorted(set(result.report.unsupported)))
                        or (("sweep ignored: vertical is unbound",) if entered_silently
                            and outcome.state.mode is ModeId.GROSS else ()),
                    )
                )
            except Exception:  # noqa: BLE001 — a HUD must never take the loop down
                pass

        intents = journal.expand(outcome.intents)
        for intent in intents:
            result.intents.append(
                EmittedIntent(window.t_end, state.mode, intent, state.confidence)
            )
            journal.record(window.t_end, intent)
            # Doing something changes the situation, which changes point C's cache key — so an
            # action is itself a context change worth prefetching against.
            if context_service is not None:
                context_service.note_action(intent.kind)
            if dump_intents:
                print(f"{window.t_end:9.1f}  {state.mode.value:<10} {intent}")

        # Grammar runs AFTER dispatch, and ADDS a compound action rather than retracting the
        # primitives that formed it.
        #
        # The alternative — holding every gesture back until the grammar window expires to see
        # whether it becomes a phrase — would add up to 1.2s of latency to every single swipe.
        # Paying that on every gesture to make a rare compound cleaner is the wrong trade; a
        # compound that also performs its parts is a little redundant, and redundant beats slow.
        for intent in intents:
            history.append((window.t_end, intent))
        if grammar.max_length:
            del history[: max(0, len(history) - grammar.max_length)]
            utterance = grammar.match(history)
            if utterance is not None:
                result.utterances.append(utterance.rule.name)
                history.clear()  # a phrase is consumed; its tail must not seed the next match
                if dump_intents:
                    print(f"{window.t_end:9.1f}  grammar    {utterance.rule.name} "
                          f"-> {utterance.rule.action}")

        if dispatch and intents:
            router.dispatch(intents, result.report)

    if first_t is not None:
        result.span_ms = last_t - first_t
    return result
