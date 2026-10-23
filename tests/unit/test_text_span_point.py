"""Jev point G — how much text the user meant to select."""

from app.decision.backends.rules import RuleProvider
from app.decision.judgment_config import load as loadj
from app.decision.points import g_text_span as G
from app.decision.provider import Judgment, Source
from app.decision.questions import PointId
from app.text_spans import TextContext

CFG = loadj().point(PointId.G_TEXT_SPAN)


def ctx(before, after):
    return TextContext(before + after, len(before), len(before), "")


def test_the_state_is_split_at_the_point_the_user_is_aiming_at():
    # The split IS the information: where the pointer landed is the whole question.
    req = G.build_request(ctx("hello ", "world"), CFG)
    assert req.state["text_before_the_point"].endswith("hello ")
    assert req.state["text_after_the_point"].startswith("world")


def test_surrounding_text_is_truncated_on_both_sides():
    # Untrusted document content, and the model degrades with irrelevant context.
    req = G.build_request(ctx("x" * 5000, "y" * 5000), CFG)
    for value in req.state.values():
        assert len(str(value)) <= CFG.max_field_chars


def test_the_default_span_is_the_smallest_safe_one():
    # Extending a selection is easy; undoing an over-selection is annoying.
    assert G.SpanChoice.default().span == "word"
    assert G.interpret({}, CFG).span == "word"


def test_a_value_outside_the_closed_set_degrades_to_word():
    answers = {"span": Judgment("span", "whole_document", 0.99, Source.JEV)}
    assert G.interpret(answers, CFG).span == "word"


def test_every_declared_option_is_a_span_the_resolver_understands():
    # A yaml option with no resolver would silently select nothing at runtime.
    for option in CFG.questions["span"].options:
        assert option in G.SPANS


def test_the_cache_key_follows_the_pointer():
    # Pointing at the same place twice should not pay twice; moving should re-ask.
    a = G.build_request(ctx("the quick brown ", "fox jumps"), CFG).cache_key
    b = G.build_request(ctx("the quick brown ", "fox jumps"), CFG).cache_key
    c = G.build_request(ctx("completely different ", "text entirely"), CFG).cache_key
    assert a == b and a != c


def test_the_fallback_recognises_structural_spans():
    # Sitting inside a URL is a fact about the text, not a judgment — a regex can own that.
    inside_url = G.interpret(
        RuleProvider().judge(G.build_request(ctx("see https://ex", "ample.com/x now"), CFG)), CFG
    )
    assert inside_url.span == "url"


def test_the_fallback_defaults_to_word_for_prose():
    plain = G.interpret(
        RuleProvider().judge(G.build_request(ctx("just some pl", "ain words"), CFG)), CFG
    )
    assert plain.span == "word"


def test_the_act_threshold_is_low_because_the_result_is_visible():
    # Like point C: the selection is shown and trivially corrected, so a medium-confidence answer
    # beats making the user wait to find out what got selected.
    a = loadj().point(PointId.A_APP_CONTEXT)
    assert CFG.act_threshold < a.act_threshold
