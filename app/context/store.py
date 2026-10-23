"""The context service: what turns five working Jev points into a system that uses them.

Every integration point was verified in isolation before this existed, and the loop still ran with
`DecisionContext.empty()` — so `app_class` was permanently `unknown`, point C was never prefetched,
and nothing Jev knew ever reached the engine. This is the wire.

It owns three things and no more:

  * the AT-SPI focus watcher, on its own GLib thread
  * a `JudgmentBroker`, which owns the ONLY thread allowed to call a provider
  * a frozen `DecisionContext` that the frame loop reads

The critical property is that `snapshot()` never blocks and never calls Jev. It returns whatever
the broker has delivered so far, with an honest `app_class_age_ms` so a guard can distrust a stale
answer. That is ADR-0001's firewall expressed as an object: the engine reads a value, it cannot
request one.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.actions import ActionCatalogue, load as load_actions
from app.decision.broker import JudgmentBroker
from app.decision.judgment_config import JudgmentConfig
from app.decision.points import a_app_context, c_radial_rank
from app.decision.questions import PointId
from app.naming import same_target
from app.types import AppClass, DecisionContext, FocusInfo, Wedge


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    focus: FocusInfo | None
    app_class: AppClass
    confidence: float
    updated_t_ms: float
    wedges: tuple[Wedge, ...]


class ContextService:
    def __init__(
        self,
        broker: JudgmentBroker,
        jcfg: JudgmentConfig,
        *,
        focus_source=None,
        cache=None,
        catalogue: ActionCatalogue | None = None,
    ) -> None:
        self._broker = broker
        self._jcfg = jcfg
        self._focus = focus_source
        self._cache = cache
        self._catalogue = catalogue or load_actions()
        self._lock = threading.Lock()
        self._snapshot = ContextSnapshot(None, AppClass.UNKNOWN, 0.0, 0.0, ())
        self._recent: list[str] = []
        self._started = time.monotonic()
        self._subscription = None

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        self._broker.start()
        if self._focus is None:
            return
        self._subscription = self._focus.subscribe(self._on_focus)
        current = self._focus.current()
        if current is not None:
            self._on_focus(current)

    def stop(self) -> None:
        if self._subscription is not None:
            try:
                self._subscription.unsubscribe()
            except Exception:  # noqa: BLE001
                pass
        self._broker.stop()

    # -- called from the loop, once per frame. Never blocks. ------------------------

    def drain(self) -> int:
        """Apply any judgments the broker has finished. Returns how many landed."""
        ready = self._broker.drain()
        for item in ready:
            if item.error or not item.answers:
                continue
            if item.point == PointId.A_APP_CONTEXT.value:
                self._apply_app_context(item.answers)
        return len(ready)

    def snapshot(self, t_ms: float) -> DecisionContext:
        with self._lock:
            snap = self._snapshot
        age = t_ms - snap.updated_t_ms if snap.focus is not None else float("inf")
        return DecisionContext(
            focus=snap.focus,
            app_class=snap.app_class,
            app_class_confidence=snap.confidence,
            # Honest staleness. A guard gating on app_class can see how old the answer is and
            # decline rather than acting on something from three windows ago.
            app_class_age_ms=age,
            active_chord=None,
            recent_actions=tuple(self._recent[-5:]),
            capabilities=frozenset(),
        )

    def wedges(self) -> tuple[Wedge, ...]:
        """The radial menu's contents right now — prefetched, so this is a cache read."""
        with self._lock:
            snap = self._snapshot
        if self._cache is None:
            return snap.wedges
        cfg = self._jcfg.point(PointId.C_RADIAL_RANK)
        ranking = c_radial_rank.lookup_cached(
            self._cache, self._catalogue, snap.app_class.value, self._recent, cfg
        )
        return ranking.wedges

    def note_action(self, action_id: str) -> None:
        """Recent actions feed point C's ranking, and change its cache key — so doing something
        is itself a context change worth prefetching against."""
        self._recent.append(action_id)
        self._prefetch_radial()

    # -- focus changes, on the AT-SPI thread ----------------------------------------

    def _on_focus(self, focus: FocusInfo) -> None:
        with self._lock:
            if same_target(self._snapshot.focus, focus):
                return
            self._snapshot = ContextSnapshot(
                focus=focus,
                # Deliberately reset to UNKNOWN rather than keeping the previous app's class:
                # carrying it over would apply the old application's gesture map to the new one
                # for however long the round trip takes.
                app_class=AppClass.UNKNOWN,
                confidence=0.0,
                updated_t_ms=self._now_ms(),
                wedges=(),
            )
        cfg = self._jcfg.point(PointId.A_APP_CONTEXT)
        self._broker.request(a_app_context.build_request(focus, cfg))
        self._prefetch_radial()

    def _prefetch_radial(self) -> None:
        cfg = self._jcfg.point(PointId.C_RADIAL_RANK)
        if not cfg.enabled:
            return
        with self._lock:
            app_class = self._snapshot.app_class.value
        c_radial_rank.prefetch(self._broker, self._catalogue, app_class, self._recent, cfg)

    def _apply_app_context(self, answers) -> None:
        cfg = self._jcfg.point(PointId.A_APP_CONTEXT)
        ctx = a_app_context.interpret(answers, cfg)
        with self._lock:
            self._snapshot = ContextSnapshot(
                focus=self._snapshot.focus,
                app_class=ctx.app_class,
                confidence=ctx.confidence,
                updated_t_ms=self._now_ms(),
                wedges=self._snapshot.wedges,
            )
        # The app class is part of point C's cache key, so learning it is itself a context change.
        self._prefetch_radial()

    def _now_ms(self) -> float:
        return (time.monotonic() - self._started) * 1000.0
