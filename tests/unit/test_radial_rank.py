"""Jev point C — adaptive radial menu.

The menu must be useful with Jev off, instant with Jev on, and never make the user wait."""

from app.actions import load as load_actions
from app.decision.backends.rules import RuleProvider
from app.decision.judgment_config import load as loadj
from app.decision.points import c_radial_rank as C
from app.decision.provider import Judgment, Source
from app.decision.questions import PointId, ScoreQ

CFG = loadj().point(PointId.C_RADIAL_RANK)
CAT = load_actions()


def test_the_menu_is_full_without_asking_anything():
    # The local ranking IS the menu. Jev only ever re-orders it.
    wedges = C.local_ranking(CAT, "presentation", [], CFG)
    assert len(wedges) == C.WEDGE_COUNT


def test_recently_used_actions_rank_first_locally():
    wedges = C.local_ranking(CAT, "presentation", ["next_slide"], CFG)
    assert wedges[0].action_id == "next_slide"


def test_only_context_appropriate_actions_are_offered():
    ids = {w.action_id for w in C.local_ranking(CAT, "terminal", [], CFG)}
    assert "next_slide" not in ids


def test_candidates_are_narrowed_before_asking_jev():
    # Scoring actions that cannot apply wastes tokens and invites a confident wrong answer.
    req = C.build_request(CAT, "terminal", [], CFG)
    assert C._key("next_slide") not in req.questions
    assert all(isinstance(q, ScoreQ) for q in req.questions.values())


def test_the_cache_key_captures_the_whole_situation():
    a = C.build_request(CAT, "terminal", ["copy"], CFG).cache_key
    b = C.build_request(CAT, "terminal", ["paste"], CFG).cache_key
    c = C.build_request(CAT, "browser", ["copy"], CFG).cache_key
    assert a != b and a != c


def test_recent_history_is_bounded():
    # A long history makes every situation look alike and the menu stops adapting — and it would
    # also make the cache key unique every time, so nothing would ever be prefetched usefully.
    long = [f"a{i}" for i in range(20)]
    key = C.build_request(CAT, "terminal", long, CFG).cache_key
    assert key.count(">") < 5


def test_a_missing_answer_degrades_to_the_local_ranking():
    # This is the dwell-time path on a cache miss. It must not raise and must not be empty.
    ranking = C.interpret({}, CAT, "presentation", ["next_slide"], CFG)
    assert ranking.source is Source.RULES
    assert ranking.wedges[0].action_id == "next_slide"
    assert not ranking.upgraded


def test_jev_scores_reorder_the_wedges():
    answers = {
        C._key(spec.id): Judgment(C._key(spec.id), 3.0 if spec.id == "play_pause" else 0.0,
                                  0.9, Source.JEV)
        for spec in CAT.for_context("media_player")
    }
    ranking = C.interpret(answers, CAT, "media_player", [], CFG)
    assert ranking.wedges[0].action_id == "play_pause"
    assert ranking.upgraded


def test_scores_are_normalised_to_zero_one():
    answers = {
        C._key(spec.id): Judgment(C._key(spec.id), float(len(C.RELEVANCE_LEVELS) - 1), 0.9, Source.JEV)
        for spec in CAT.for_context("media_player")
    }
    for wedge in C.interpret(answers, CAT, "media_player", [], CFG).wedges:
        assert 0.0 <= wedge.score <= 1.0


def test_the_prefetch_budget_is_far_larger_than_the_dwell():
    # Deliberate. This request is always issued on context change, never while the user waits —
    # a 250ms budget timed out on every call and the user never once saw a Jev-ranked menu.
    from app.config import load as load_config

    dwell = load_config(use_env=False).arbitration.hold_ms
    from app.types import ModeId

    assert CFG.timeout_ms > dwell[ModeId.MACRO]


def test_the_offline_fallback_matches_the_local_ranking():
    # `--offline` must not be a different menu, just an unranked one.
    req = C.build_request(CAT, "presentation", ["next_slide"], CFG)
    ranking = C.interpret(RuleProvider().judge(req), CAT, "presentation", ["next_slide"], CFG)
    assert ranking.wedges[0].action_id == "next_slide"
