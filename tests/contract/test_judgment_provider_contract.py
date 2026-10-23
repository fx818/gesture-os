"""Contract every JudgmentProvider must satisfy.

Rules and Replay run in CI. TypeSafeProvider joins the same list under `-m live`, which is the
reason for writing this as a contract suite rather than per-backend tests."""

import pytest

from app.decision.backends.replay import ReplayProvider
from app.decision.backends.rules import RuleProvider
from app.decision.provider import Judgment, JudgmentProvider, JudgmentRequest, Source
from app.decision.questions import ChoiceQ, NoulQ, PointId
import app.decision.points.a_app_context  # noqa: F401  — registers the rules fallback

QUESTIONS = {
    "app_class": ChoiceQ("i", {"terminal": "t", "browser": "b", "unknown": "u"}),
    "is_text_entry": NoulQ("i"),
}


def _req(app="ptyxis", title="claude"):
    return JudgmentRequest(
        PointId.A_APP_CONTEXT,
        {"application_name": app, "window_title": title},
        QUESTIONS,
        cache_key=f"{app}|{title}|r1",
    )


def _providers():
    return [RuleProvider(), ReplayProvider(strict=False)]


@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
def test_provider_satisfies_the_protocol(provider):
    assert isinstance(provider, JudgmentProvider)


@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
def test_health_is_reportable_before_any_call(provider):
    # wiring.py asks for health at startup to decide what to show on the HUD.
    h = provider.health()
    assert h.name and isinstance(h.available, bool)


@pytest.mark.parametrize("provider", _providers(), ids=lambda p: type(p).__name__)
def test_answers_are_judgments_with_a_confidence_in_range(provider):
    for key, j in provider.judge(_req()).items():
        assert isinstance(j, Judgment)
        assert j.key == key
        assert 0.0 <= j.confidence <= 1.0, f"{key} reported {j.confidence}"
        assert isinstance(j.source, Source)


def test_rules_provider_answers_every_question_it_was_asked():
    # A provider that silently drops a question would make a caller see a missing key rather than
    # a low-confidence answer, and the confidence gate would never get the chance to fire.
    assert set(RuleProvider().judge(_req())) == set(QUESTIONS)


def test_rules_provider_never_raises_for_a_point_with_no_fallback():
    # Every point now registers a fallback, so this exercises the mechanism directly: an
    # unregistered point must answer "least-committal, zero confidence" rather than explode.
    from app.decision.backends.rules import _unknown

    req = JudgmentRequest(PointId.G_TEXT_SPAN, {"x": "y"}, QUESTIONS, cache_key="k")
    out = _unknown(req)
    assert set(out) == set(QUESTIONS)
    assert all(j.confidence == 0.0 for j in out.values())
    assert out["app_class"].value == "unknown"


def test_rules_confidence_is_honest_about_not_knowing():
    # A flattering confidence here would silently promote a guess into an automatic action,
    # because the gate downstream is the same code path for every source.
    out = RuleProvider().judge(_req(app="some-unknown-app", title=""))
    assert out["app_class"].value == "unknown"
    assert out["app_class"].confidence == 0.0


def test_rules_confidence_is_capped_by_the_class_it_derives_from():
    # is_text_entry is inferred FROM app_class, so it can never be more certain than app_class.
    out = RuleProvider().judge(_req(app="ptyxis"))
    assert out["is_text_entry"].confidence <= out["app_class"].confidence
