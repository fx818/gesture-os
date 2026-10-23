"""Jev point C — rank the action library down to the wedges that fit on a radial menu.

The scope doc's own open question is how many gestures a person can actually memorise. A radial
menu is the hedge: 8 wedges reachable by direction, drawn from a library far larger than anyone
could remember as distinct poses. Which 8 is the interesting part.

**The static ranking is the primary path and Jev is an upgrade** — this inverts the original plan,
for a measured reason (ADR-0004). Jev's p50 here is ~390ms and p95 ~650ms, while the whole macro
dwell is 400-500ms. A blocking call would leave the menu empty or late at the exact moment the
user is looking at it.

So: local wedges render immediately from recency and app context (both free, both already in
`DecisionContext`), and the menu works identically with Jev disabled.

**The ranking is PREFETCHED on context change, not requested at dwell start.** Issuing it when the
menu opens does not work and measurement said so plainly: 540ms against a 250ms budget meant the
call timed out every single time and the fallback's numbers were all the user ever saw. But the
cache key is `app_class | recent_actions`, and both are known the moment focus changes — seconds
before any dwell begins. Prefetching there turns the dwell-time lookup into a cache hit at
effectively zero latency.

It is worth prefetching because Jev measurably beats the local ranking: for a media player with no
recency signal at all, it put "Play or pause" first where recency-plus-catalogue-order had it
fourth. It knows what applications are FOR, which is precisely the thing a local heuristic cannot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.actions import ActionCatalogue, ActionSpec
from app.decision.backends.rules import register
from app.decision.judgment_config import PointConfig
from app.decision.provider import Judgment, JudgmentRequest, Source
from app.decision.questions import PointId, ScoreQ
from app.types import Wedge

POINT = PointId.C_RADIAL_RANK

WEDGE_COUNT = 8  # tuning-exempt: a radial menu's geometry, not a threshold

# Ordered low to high; a Score returns a position on this rubric, not a category.
RELEVANCE_LEVELS = (
    "Not something the user would plausibly want here.",
    "Occasionally useful in this application, but not now.",
    "Plausible next action given what they are doing.",
    "Very likely the action they are reaching for right now.",
)


@dataclass(frozen=True, slots=True)
class Ranking:
    wedges: tuple[Wedge, ...]
    source: Source
    upgraded: bool  # True when Jev returned in time and changed the order


def prefetch(
    broker,
    catalogue: ActionCatalogue,
    app_class: str,
    recent: Sequence[str],
    cfg: PointConfig,
) -> bool:
    """Warm the cache for the situation the user is in now.

    Called on context change (focus change, or after an action), never at dwell start. Returns
    False when an identical request is already in flight — the broker coalesces, so alt-tabbing
    quickly does not queue a round trip per window.
    """
    return broker.request(build_request(catalogue, app_class, recent, cfg))


def lookup_cached(
    cache, catalogue: ActionCatalogue, app_class: str, recent: Sequence[str], cfg: PointConfig
) -> Ranking:
    """The dwell-time read. Cache only — it CANNOT block, by construction.

    On a miss it returns the local ranking, which is what the menu was already showing. The user
    never waits on this path and never sees an empty menu.
    """
    request = build_request(catalogue, app_class, recent, cfg)
    answers = cache.get(POINT.value, request.cache_key, cfg.cache_ttl_s) or {}
    return interpret(answers, catalogue, app_class, recent, cfg)


def _key(action_id: str) -> str:
    """Question keys must be stable and safe; action ids already are."""
    return f"a_{action_id}"


def build_request(
    catalogue: ActionCatalogue,
    app_class: str,
    recent: Sequence[str],
    cfg: PointConfig,
) -> JudgmentRequest:  # noqa: D401
    """One call, one Score per candidate — speculative fan-out.

    Candidates are narrowed to the current context FIRST. Scoring actions that cannot apply here
    wastes tokens and invites a confident wrong answer that a filter makes impossible.
    """
    depth = int(cfg.fallback.value("recent_history_depth"))
    recent = list(recent)[-depth:] if depth else []
    candidates = catalogue.for_context(app_class)
    questions = {
        _key(a.id): ScoreQ(
            instructions=f"{cfg.questions['relevance'].instructions}\n\nAction: {a.description}",
            levels=RELEVANCE_LEVELS,
        )
        for a in candidates
    }
    return JudgmentRequest(
        point=POINT,
        state={
            "application_kind": app_class,
            "recent_actions": ", ".join(recent) or "none yet this session",
        },
        questions=questions,
        # Keyed on context + recent history: the same situation should not pay for a second
        # round trip, and the situation changes as soon as the user does something.
        cache_key=f"{app_class}|{'>'.join(recent)}|r{cfg.rev}",
        rev=cfg.rev,
    )


def local_ranking(
    catalogue: ActionCatalogue,
    app_class: str,
    recent: Sequence[str],
    cfg: PointConfig | None = None,
) -> tuple[Wedge, ...]:
    """The wedges shown immediately, with no network and no waiting.

    Recency first — the strongest available signal for "what next" without asking anything — then
    catalogue order, which a human curated. Good enough that the menu is useful on its own.
    """
    if cfg is None:
        from app.decision.judgment_config import load as _load_judgment

        cfg = _load_judgment().point(POINT)
    base = cfg.fallback.value("base_score")
    decay = cfg.fallback.value("recency_decay")

    candidates = list(catalogue.for_context(app_class))
    recent_rank = {action_id: i for i, action_id in enumerate(reversed(list(recent)))}

    def score(spec: ActionSpec) -> float:
        if spec.id in recent_rank:
            return 1.0 - (recent_rank[spec.id] * decay)
        return base

    ordered = sorted(candidates, key=lambda s: (-score(s), s.id))
    return tuple(
        Wedge(action_id=s.id, label=s.label, score=score(s)) for s in ordered[:WEDGE_COUNT]
    )


def interpret(
    answers: Mapping[str, Judgment],
    catalogue: ActionCatalogue,
    app_class: str,
    recent: Sequence[str],
    cfg: PointConfig | None = None,
) -> Ranking:
    fallback = local_ranking(catalogue, app_class, recent, cfg)
    if not answers:
        return Ranking(fallback, Source.RULES, upgraded=False)

    scored: list[tuple[float, ActionSpec]] = []
    for spec in catalogue.for_context(app_class):
        judgment = answers.get(_key(spec.id))
        if judgment is None or not isinstance(judgment.value, (int, float)):
            continue
        # Score is a position on the rubric, 0..len(levels)-1; normalise so wedges are comparable.
            # Normalise the rubric position (0..len-1) to 0..1 so wedges are comparable
        # with the local ranking's scores.
        scored.append((float(judgment.value) / (len(RELEVANCE_LEVELS) - 1), spec))

    if not scored:
        return Ranking(fallback, Source.RULES, upgraded=False)

    scored.sort(key=lambda kv: (-kv[0], kv[1].id))
    wedges = tuple(
        Wedge(action_id=spec.id, label=spec.label, score=round(value, 3))  # tuning-exempt: display rounding
        for value, spec in scored[:WEDGE_COUNT]
    )
    source = next(iter(answers.values())).source
    order_changed = [w.action_id for w in wedges] != [w.action_id for w in fallback]
    return Ranking(wedges, source, upgraded=order_changed)


# --------------------------------------------------------------------------------------
# Offline fallback — the same local ranking, so `--offline` is not a different menu
# --------------------------------------------------------------------------------------


@register(POINT)
def fallback(req: JudgmentRequest) -> Mapping[str, Judgment]:
    from app.actions import load as load_actions
    from app.decision.judgment_config import load as _load_judgment

    fb = _load_judgment().point(POINT).fallback
    catalogue = load_actions()
    app_class = str(req.state.get("application_kind", "any"))
    recent = [r.strip() for r in str(req.state.get("recent_actions", "")).split(",") if r.strip()]

    ranked = {w.action_id: w.score for w in local_ranking(catalogue, app_class, recent)}
    top = (len(RELEVANCE_LEVELS) - 1) * fb.value("local_top_level_fraction")
    return {
        _key(spec.id): Judgment(
            _key(spec.id),
            top * ranked.get(spec.id, 0.0),
            fb.value("local_confidence"),
            Source.RULES,
        )
        for spec in catalogue.for_context(app_class)
    }
