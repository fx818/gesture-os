"""Golden intent streams — the regression net for behaviour.

Unit tests catch a broken predicate. These catch "the swipe now fires twice" and "the cursor
flickers", which is the failure mode the scope doc names as its #1 risk and which no assertion
about a single function would notice.

`python main.py golden --update` regenerates them. Always read the diff: it IS the change.
"""

import pytest

from app.runtime import golden


@pytest.mark.parametrize("fixture", golden.fixtures(), ids=lambda p: p.name.split(".")[0])
def test_intent_stream_matches_golden(fixture):
    ok, expected, actual = golden.check(fixture)
    if not ok:
        exp, act = expected.splitlines(), actual.splitlines()
        diff = []
        for i in range(max(len(exp), len(act))):
            e = exp[i] if i < len(exp) else "(missing)"
            a = act[i] if i < len(act) else "(missing)"
            if e != a:
                diff.append(f"line {i + 1}:\n  expected: {e}\n  actual:   {a}")
                if len(diff) >= 3:
                    break
        pytest.fail(
            f"{fixture.name} behaviour changed ({len(exp)} -> {len(act)} events).\n"
            + "\n".join(diff)
            + "\n\nIf intended: python main.py golden --update"
        )


def test_replay_is_deterministic():
    # Everything downstream of this assumption breaks silently if it stops holding: golden files,
    # calibration, and any bug report that says "replay this fixture".
    fixture = golden.SESSIONS / "precision-trace.ndjson.gz"
    assert golden.render(golden.replay_fixture(fixture)) == golden.render(
        golden.replay_fixture(fixture)
    )
