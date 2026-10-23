"""The one place backends are constructed.

Everything else receives ports. `--offline`, a missing key, or GESTURE_OS_OFFLINE all select the
rules-only composition here, and no other code knows the difference.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.config import offline_requested
from app.decision.backends.rules import RuleProvider
from app.decision.cache import DEFAULT_CACHE_PATH, SqliteCache
from app.decision.composite import BudgetedProvider, CachingProvider, FallbackProvider
from app.decision.judgment_config import JudgmentConfig, PointConfig
from app.decision.provider import JudgmentProvider

# Importing the point modules registers their rules fallbacks. Explicit, because an unregistered
# fallback silently degrades to "unknown at 0.0" rather than failing.
import app.decision.points.a_app_context  # noqa: F401


def judgment_available(force_offline: bool = False) -> bool:
    return not (force_offline or offline_requested() or not os.environ.get("TYPESAFE_API_KEY"))


def build_judgment_provider(
    jcfg: JudgmentConfig,
    point: PointConfig,
    *,
    force_offline: bool = False,
    use_cache: bool = True,
    cache_path: Path = DEFAULT_CACHE_PATH,
    cache: SqliteCache | None = None,
) -> JudgmentProvider:
    """`force_offline` means "do not touch the network" — it deliberately still serves the cache,
    because a cached answer is offline-safe and is what makes the product usable without a key.

    `use_cache=False` is separate and exists to see what the underlying provider actually says:
    without it, "does the rules fallback still work?" is unanswerable once anything is cached."""
    rules = RuleProvider()
    store = cache if cache is not None else SqliteCache(cache_path)

    if not judgment_available(force_offline):
        return CachingProvider(rules, store, ttl_s=point.cache_ttl_s) if use_cache else rules

    from app.decision.backends.typesafe import TypeSafeProvider

    live = TypeSafeProvider(
        timeout_s=point.timeout_ms / 1000.0,
        max_state_chars=point.max_state_chars,
    )
    stack = BudgetedProvider(
        FallbackProvider(live, rules, act_threshold=point.act_threshold),
        per_minute=jcfg.rate_limit_per_min,
    )
    return CachingProvider(stack, store, ttl_s=point.cache_ttl_s) if use_cache else stack
