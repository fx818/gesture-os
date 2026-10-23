"""Gesture grammar — compound phrases over the primitive gestures."""

import pytest

from app.arbitration.grammar import Grammar, GrammarRule, load
from app.intents import ButtonPress, Button, Direction, RunMacro, SwitchWindow


def _hist(*pairs):
    return [(t, i) for t, i in pairs]


def test_the_shipped_grammar_loads():
    g = load()
    assert g.rules and g.max_length >= 2


def test_a_phrase_matches_within_its_window():
    g = load()
    m = g.match(_hist((0.0, SwitchWindow(Direction.LEFT)), (500.0, SwitchWindow(Direction.LEFT))))
    assert m is not None and m.rule.name == "double-left"


def test_the_same_primitives_too_far_apart_are_not_a_phrase():
    # The time window IS the safety mechanism: without it any two gestures would eventually match.
    g = load()
    assert g.match(_hist((0.0, SwitchWindow(Direction.LEFT)),
                         (9000.0, SwitchWindow(Direction.LEFT)))) is None


def test_a_single_gesture_is_never_a_phrase():
    g = load()
    assert g.match(_hist((0.0, SwitchWindow(Direction.LEFT)))) is None


def test_empty_history_matches_nothing():
    assert load().match([]) is None


def test_the_longest_matching_rule_wins():
    # Otherwise a two-step rule shadows a three-step one that extends it — the same reason a
    # lexer prefers the longest token.
    short = GrammarRule("short", ("A", "B"), 1000, "x")
    long = GrammarRule("long", ("Z", "A", "B"), 1000, "y")
    g = Grammar((short, long))

    class I:
        def __init__(self, kind): self.kind = kind

    m = g.match([(0.0, I("Z")), (100.0, I("A")), (200.0, I("B"))])
    assert m.rule.name == "long"


def test_a_one_step_rule_is_rejected_at_load(tmp_path):
    # A one-step "phrase" is just a gesture, and would fire on every occurrence of it.
    p = tmp_path / "grammar.yaml"
    p.write_text("defaults:\n  within_ms: 1000\nrules:\n  - name: bad\n    sequence: [A]\n    action: x\n")
    with pytest.raises(ValueError, match="fewer than two"):
        load(p)


def test_a_rule_with_no_time_window_is_rejected(tmp_path):
    p = tmp_path / "grammar.yaml"
    p.write_text("rules:\n  - name: bad\n    sequence: [A, B]\n    action: x\n")
    with pytest.raises(ValueError, match="time window"):
        load(p)


def test_a_missing_grammar_file_is_not_an_error(tmp_path):
    # Grammar is optional; its absence must not stop the system starting.
    assert load(tmp_path / "nope.yaml").rules == ()


def test_rules_inherit_the_default_window(tmp_path):
    p = tmp_path / "grammar.yaml"
    p.write_text("defaults:\n  within_ms: 750\nrules:\n  - name: r\n    sequence: [A, B]\n    action: x\n")
    assert load(p).rules[0].within_ms == 750
