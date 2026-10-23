"""The provider decorator stack.

These encode behaviour that was got wrong once already and cost real latency: a cacheability rule
that looked conservative and meant nothing was ever cached.
"""

import pytest

from app.decision.cache import SqliteCache
from app.decision.composite import BudgetedProvider, CachingProvider, FallbackProvider
from app.decision.provider import (
    Judgment,
    JudgmentRequest,
    ProviderError,
    ProviderHealth,
    Source,
)
from app.decision.questions import ChoiceQ, PointId

Q = {"app_class": ChoiceQ("i", {"terminal": "t", "browser": "b", "unknown": "u"})}


def _req(key="k"):
    return JudgmentRequest(PointId.A_APP_CONTEXT, {"application_name": "ptyxis"}, Q, cache_key=key)


class Fake:
    """A provider whose answers and failures are scripted."""

    def __init__(self, answers=None, *, fail=False):
        self.answers = answers or {}
        self.fail = fail
        self.calls = 0

    def judge(self, req):
        self.calls += 1
        if self.fail:
            raise ProviderError("scripted failure")
        return self.answers

    def health(self):
        return ProviderHealth(name="fake", available=not self.fail, calls=self.calls)


def _j(key, value, conf, source):
    return Judgment(key=key, value=value, confidence=conf, source=source)


@pytest.fixture
def cache(tmp_path):
    return SqliteCache(tmp_path / "c.sqlite")


# --- caching ---------------------------------------------------------------------------


def test_second_identical_request_is_served_from_cache(cache):
    inner = Fake({"app_class": _j("app_class", "terminal", 1.0, Source.JEV)})
    p = CachingProvider(inner, cache)
    assert p.judge(_req())["app_class"].source is Source.JEV
    again = p.judge(_req())
    assert again["app_class"].source is Source.CACHE
    assert inner.calls == 1, "the second call must not reach the provider"


def test_a_result_containing_one_fallback_answer_is_still_cached(cache):
    # THE REGRESSION. A point that fans out several questions will routinely have one fall back
    # (a Noul whose derived confidence is low). Refusing to cache the whole result then meant
    # NOTHING was ever cached and every focus change paid a full ~1.2s round trip.
    inner = Fake({
        "app_class": _j("app_class", "terminal", 1.0, Source.JEV),
        "is_text_entry": _j("is_text_entry", 1.0, 0.8, Source.RULES),
    })
    p = CachingProvider(inner, cache)
    p.judge(_req())
    assert p.judge(_req())["app_class"].source is Source.CACHE
    assert inner.calls == 1


def test_a_total_outage_is_never_cached(cache):
    # Every answer from rules means Jev was unreachable. Caching that would keep serving a
    # degraded answer long after the service came back.
    inner = Fake({"app_class": _j("app_class", "terminal", 0.85, Source.RULES)})
    p = CachingProvider(inner, cache)
    p.judge(_req())
    p.judge(_req())
    assert inner.calls == 2


def test_different_cache_keys_do_not_collide(cache):
    inner = Fake({"app_class": _j("app_class", "terminal", 1.0, Source.JEV)})
    p = CachingProvider(inner, cache)
    p.judge(_req("a"))
    p.judge(_req("b"))
    assert inner.calls == 2


def test_a_request_with_no_cache_key_is_never_cached(cache):
    inner = Fake({"app_class": _j("app_class", "terminal", 1.0, Source.JEV)})
    p = CachingProvider(inner, cache)
    p.judge(JudgmentRequest(PointId.A_APP_CONTEXT, {}, Q))
    p.judge(JudgmentRequest(PointId.A_APP_CONTEXT, {}, Q))
    assert inner.calls == 2


def test_expired_entries_are_refetched(cache):
    inner = Fake({"app_class": _j("app_class", "terminal", 1.0, Source.JEV)})
    p = CachingProvider(inner, cache, ttl_s=0.0001)
    p.judge(_req())
    import time

    time.sleep(0.01)
    p.judge(_req())
    assert inner.calls == 2


def test_cache_survives_a_new_process(tmp_path):
    # The cache is the thing that makes a 375ms judgment invisible on the second focus change,
    # so it has to outlive the process that filled it.
    path = tmp_path / "c.sqlite"
    inner = Fake({"app_class": _j("app_class", "terminal", 1.0, Source.JEV)})
    CachingProvider(inner, SqliteCache(path)).judge(_req())
    fresh = CachingProvider(Fake({}), SqliteCache(path))
    assert fresh.judge(_req())["app_class"].source is Source.CACHE


# --- budget ----------------------------------------------------------------------------


def test_budget_refuses_past_the_per_minute_limit():
    inner = Fake({"app_class": _j("app_class", "terminal", 1.0, Source.JEV)})
    p = BudgetedProvider(inner, per_minute=2)
    p.judge(_req())
    p.judge(_req())
    with pytest.raises(ProviderError, match="rate budget"):
        p.judge(_req())


def test_budget_refuses_past_the_session_cap():
    p = BudgetedProvider(Fake({}), per_minute=1000, session_cap=1)
    p.judge(_req())
    with pytest.raises(ProviderError, match="session budget"):
        p.judge(_req())


def test_budget_refusal_is_a_provider_error_so_fallback_catches_it():
    # A 429 must degrade to rules, not stall a caller waiting on the network.
    rules = Fake({"app_class": _j("app_class", "terminal", 0.85, Source.RULES)})
    p = FallbackProvider(BudgetedProvider(Fake({}), per_minute=0), rules)
    assert p.judge(_req())["app_class"].source is Source.RULES


# --- fallback --------------------------------------------------------------------------


def test_primary_failure_falls_back():
    rules = Fake({"app_class": _j("app_class", "terminal", 0.85, Source.RULES)})
    p = FallbackProvider(Fake(fail=True), rules)
    assert p.judge(_req())["app_class"].value == "terminal"
    assert p.fallbacks == 1


def test_a_confident_primary_answer_is_not_second_guessed():
    rules = Fake({"app_class": _j("app_class", "browser", 0.99, Source.RULES)})
    p = FallbackProvider(
        Fake({"app_class": _j("app_class", "terminal", 0.95, Source.JEV)}), rules,
        act_threshold=0.9,
    )
    assert p.judge(_req())["app_class"].value == "terminal"
    assert rules.calls == 0


def test_a_more_confident_rule_beats_an_uncertain_model_answer():
    # The measured case: Jev returned `unknown` at 0.53 for ptyxis, a terminal it does not know by
    # name. A two-line regex that does know it should win.
    p = FallbackProvider(
        Fake({"app_class": _j("app_class", "unknown", 0.53, Source.JEV)}),
        Fake({"app_class": _j("app_class", "terminal", 0.85, Source.RULES)}),
        act_threshold=0.9,
    )
    got = p.judge(_req())["app_class"]
    assert got.value == "terminal" and got.source is Source.RULES


def test_a_rule_that_knows_nothing_never_displaces_the_model():
    # The inverse, and the more dangerous direction: a 0.0 "unknown" from the rules table must not
    # overwrite a real if imperfect answer.
    p = FallbackProvider(
        Fake({"app_class": _j("app_class", "browser", 0.70, Source.JEV)}),
        Fake({"app_class": _j("app_class", "unknown", 0.0, Source.RULES)}),
        act_threshold=0.9,
    )
    got = p.judge(_req())["app_class"]
    assert got.value == "browser" and got.source is Source.JEV


def test_per_key_merge_does_not_discard_a_confident_sibling():
    # One uncertain question in a fan-out must not drag its confident siblings into the fallback.
    p = FallbackProvider(
        Fake({
            "app_class": _j("app_class", "terminal", 1.0, Source.JEV),
            "is_text_entry": _j("is_text_entry", 0.6, 0.2, Source.JEV),
        }),
        Fake({
            "app_class": _j("app_class", "unknown", 0.0, Source.RULES),
            "is_text_entry": _j("is_text_entry", 1.0, 0.85, Source.RULES),
        }),
        act_threshold=0.9,
    )
    got = p.judge(_req())
    assert got["app_class"].source is Source.JEV
    assert got["is_text_entry"].source is Source.RULES


def test_the_whole_stack_is_available_with_no_network_at_all():
    # The --offline guarantee, composed exactly as runtime/wiring.py composes it.
    rules = Fake({"app_class": _j("app_class", "terminal", 0.85, Source.RULES)})
    p = FallbackProvider(BudgetedProvider(Fake(fail=True)), rules)
    assert p.judge(_req())["app_class"].value == "terminal"
    assert p.health().available is True
