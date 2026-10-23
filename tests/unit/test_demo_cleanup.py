"""Jev point D — cleaning a teach-by-demonstration recording."""

from app.decision.backends.rules import RuleProvider
from app.decision.judgment_config import load as loadj
from app.decision.points import d_demo_cleanup as D
from app.decision.provider import Judgment, Source
from app.decision.questions import ChoiceQ, NoulQ, PointId
from app.types import UiAction
from app.ui_actions import describe, render

CFG = loadj().point(PointId.D_DEMO_CLEANUP)


def _a(t, verb="focus", role="push button", name="Export", app="Figma"):
    return UiAction(t, verb, role, name, app)


STEPS = [_a(0, "activate", "frame", "design.fig", "Figma"), _a(100), _a(200, name="Slack", app="Slack")]


def test_one_call_carries_every_judgment_about_the_recording():
    # Speculative fan-out: per-step, per-existing-macro, and the pose, in a single round trip.
    req = D.build_request("x", STEPS, {"other": [_a(0)]}, ["fist", "point"], CFG)
    assert len([k for k in req.questions if k.startswith("step_")]) == len(STEPS)
    assert "dup_other" in req.questions
    assert "pose" in req.questions


def test_a_single_unbound_pose_is_not_turned_into_a_choice():
    # A Choice needs alternatives, and with one pose there is nothing to judge — asking would be
    # both wasteful and structurally invalid.
    req = D.build_request("x", STEPS, {}, ["fist"], CFG)
    assert "pose" not in req.questions


def test_steps_are_judged_by_number_against_the_full_list():
    # Judged in isolation, every step looked incidental — the noul saturated at 1.00 for six
    # heterogeneous steps including the final button click. Context is what makes it answerable.
    req = D.build_request("x", STEPS, {}, [], CFG)
    assert "recorded_steps" in req.state
    assert render(STEPS) == req.state["recorded_steps"]
    assert "step 1" in req.questions["step_0"].instructions


def test_the_state_contains_no_timestamps_or_widget_ids():
    # Jev reads prose. A timestamp is a number it cannot compare and a widget id means nothing.
    req = D.build_request("x", STEPS, {}, [], CFG)
    blob = " ".join(str(v) for v in req.state.values())
    assert "t_ms" not in blob and "0.0" not in blob


def test_incidental_steps_are_dropped_and_the_rest_kept():
    answers = {
        "step_0": Judgment("step_0", 0.1, 0.8, Source.JEV),
        "step_1": Judgment("step_1", 0.2, 0.8, Source.JEV),
        "step_2": Judgment("step_2", 1.0, 0.9, Source.JEV),
    }
    cleaned = D.interpret(answers, "x", STEPS, {}, CFG)
    assert len(cleaned.steps) == 2
    assert cleaned.dropped[0].app_name == "Slack"


def test_a_duplicate_workflow_is_flagged():
    answers = {"dup_existing": Judgment("dup_existing", 0.95, 0.9, Source.JEV)}
    cleaned = D.interpret(answers, "x", [], {"existing": []}, CFG)
    assert cleaned.is_duplicate and cleaned.duplicate_of == "existing"


def test_no_answers_keeps_everything():
    # The safe direction: a workflow with a spare step is annoying, one missing a step is broken.
    cleaned = D.interpret({}, "x", STEPS, {}, CFG)
    assert len(cleaned.steps) == len(STEPS)
    assert cleaned.dropped == ()


def test_the_fallback_spots_an_interruption_but_not_a_misclick():
    # A regex can see that Slack is not part of a Figma workflow. It cannot see that the Edit menu
    # was the wrong one — that is the judgment this point exists for, and it says so by keeping it.
    req = D.build_request("x", STEPS, {}, [], CFG)
    answers = RuleProvider().judge(req)
    cleaned = D.interpret(answers, "x", STEPS, {}, CFG)
    assert [s.app_name for s in cleaned.dropped] == ["Slack"]


def test_the_fallback_never_claims_a_duplicate():
    # Comparing two workflows for sameness is semantic; guessing would silently discard a macro.
    req = D.build_request("x", [], {"other": [_a(0)]}, [], CFG)
    answers = RuleProvider().judge(req)
    assert answers["dup_other"].confidence == 0.0


def test_recordings_are_never_cached():
    assert D.build_request("x", STEPS, {}, [], CFG).cache_key == ""
