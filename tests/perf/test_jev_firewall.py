"""ADR-0001 as an executable test.

The rule "Jev is never on the per-frame path" is enforced four ways. Three are structural
(import-linter, the broker owning the only provider thread, DecisionContext being a frozen input).
This is the fourth, and the one that catches a future edit that routes around the other three.
"""

import ast
import threading
from pathlib import Path

from app.decision.backends.rules import RuleProvider
from app.decision.broker import JudgmentBroker
from app.decision.provider import JudgmentRequest
from app.decision.questions import ChoiceQ, PointId

REPO_ROOT = Path(__file__).resolve().parents[2]
Q = {"app_class": ChoiceQ("i", {"a": "A", "unknown": "U"})}


def _req(key="k"):
    return JudgmentRequest(PointId.A_APP_CONTEXT, {"application_name": "x"}, Q, cache_key=key)


def test_no_judgment_calls_are_made_from_a_loop_thread():
    broker = JudgmentBroker(RuleProvider())
    broker.start()
    try:
        # This is what the frame loop is allowed to do: enqueue and drain, never block.
        for i in range(50):
            broker.request(_req(f"k{i}"))
        deadline = threading.Event()
        drained = []
        while len(drained) < 50 and not deadline.wait(0.01):
            drained.extend(broker.drain())
            if len(drained) >= 50:
                break
    finally:
        broker.stop()
    assert broker.calls_from_loop_thread == 0
    assert len(drained) == 50


def test_requests_are_coalesced_by_key():
    # Alt-tabbing quickly through five windows and back must not queue five round trips for the
    # one you land on.
    broker = JudgmentBroker(RuleProvider())
    accepted = [broker.request(_req("same")) for _ in range(5)]
    assert accepted.count(True) == 1


def test_request_returns_immediately_even_with_a_slow_provider():
    # The frame loop has a ~33ms budget. request() must not inherit the provider's latency.
    import time

    class Slow:
        def judge(self, req):
            time.sleep(0.5)
            return {}

        def health(self):
            from app.decision.provider import ProviderHealth

            return ProviderHealth(name="slow", available=True)

    broker = JudgmentBroker(Slow())
    broker.start()
    try:
        t0 = time.monotonic()
        broker.request(_req())
        elapsed_ms = (time.monotonic() - t0) * 1000
    finally:
        broker.stop(timeout=1.0)
    assert elapsed_ms < 10, f"request() blocked for {elapsed_ms:.0f}ms"


def test_a_failing_provider_does_not_kill_the_worker():
    # A judgment failure must surface as an error on the result, not as a dead thread that
    # silently stops answering for the rest of the session.
    class Broken:
        def judge(self, req):
            raise RuntimeError("boom")

        def health(self):
            from app.decision.provider import ProviderHealth

            return ProviderHealth(name="broken", available=False)

    broker = JudgmentBroker(Broken())
    broker.start()
    try:
        broker.request(_req("a"))
        import time

        time.sleep(0.2)
        first = broker.drain()
        broker.request(_req("b"))
        time.sleep(0.2)
        second = broker.drain()
    finally:
        broker.stop()
    assert first and first[0].error
    assert second, "the worker stopped answering after one failure"


def test_arbitration_and_features_do_not_import_the_decision_layer():
    # import-linter covers this too, but this test names the specific rule and fails with a
    # readable message that points at ADR-0001.
    offenders = []
    for directory in ("app/arbitration", "app/features"):
        for path in (REPO_ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for m in mods:
                    if m.startswith(("app.decision", "app.effectors", "typesafe", "httpx", "requests")):
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} imports {m}")
    assert not offenders, "ADR-0001 violated:\n" + "\n".join(offenders)
