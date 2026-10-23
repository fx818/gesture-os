"""points.yaml is the human-review surface for every Jev question. Its loader has to refuse
anything that would silently misbehave."""

import pytest
import yaml

from app.decision.judgment_config import JudgmentConfigError, load
from app.decision.judgment_config import POINTS_PATH
from app.decision.questions import ChoiceQ, NoulQ, PointId


def test_the_shipped_file_loads():
    cfg = load()
    a = cfg.point(PointId.A_APP_CONTEXT)
    assert a.enabled and a.rev >= 1
    assert isinstance(a.questions["app_class"], ChoiceQ)
    assert isinstance(a.questions["is_text_entry"], NoulQ)


def test_every_point_is_listed_even_when_disabled(tmp_path):
    # points.yaml is meant to be the full map of the Jev surface. A point missing entirely would
    # read as "not planned" rather than "not built yet".
    raw = yaml.safe_load(POINTS_PATH.read_text())
    assert set(raw["points"]) == {p.value for p in PointId}


def test_a_missing_point_is_rejected(tmp_path):
    raw = yaml.safe_load(POINTS_PATH.read_text())
    del raw["points"]["g_text_span"]
    p = tmp_path / "points.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(JudgmentConfigError, match="missing"):
        load(p)


def test_an_enabled_point_with_no_questions_is_rejected(tmp_path):
    # Finds whichever point is still unbuilt rather than naming one. Hardcoding a name meant this
    # test broke every time a point got built — twice already — which is noise, not signal.
    raw = yaml.safe_load(POINTS_PATH.read_text())
    unbuilt = next(
        (name for name, spec in raw["points"].items() if not (spec or {}).get("questions")), None
    )
    if unbuilt is None:
        pytest.skip("every point now defines questions; nothing left to test this against")
    raw["points"][unbuilt]["enabled"] = True
    p = tmp_path / "points.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(JudgmentConfigError, match="no questions"):
        load(p)


def test_a_choice_with_one_option_is_rejected(tmp_path):
    raw = yaml.safe_load(POINTS_PATH.read_text())
    raw["points"]["a_app_context"]["questions"]["app_class"]["options"] = {"only": "one"}
    p = tmp_path / "points.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(JudgmentConfigError, match="two options"):
        load(p)


def test_a_question_with_empty_instructions_is_rejected(tmp_path):
    raw = yaml.safe_load(POINTS_PATH.read_text())
    raw["points"]["a_app_context"]["questions"]["app_class"]["instructions"] = "   "
    p = tmp_path / "points.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(JudgmentConfigError, match="no instructions"):
        load(p)


def test_point_defaults_are_inherited_and_overridable():
    # Every point now overrides act_threshold — each one has a different cost of being wrong —
    # so inheritance is checked on a key none of them override.
    cfg = load()
    import yaml

    raw = yaml.safe_load(POINTS_PATH.read_text())
    default_budget = raw["defaults"]["max_state_chars"]
    for point in PointId:
        spec = raw["points"][point.value]
        if "max_state_chars" not in spec:
            assert cfg.point(point).max_state_chars == default_budget, point

    a = cfg.point(PointId.A_APP_CONTEXT)
    g = cfg.point(PointId.G_TEXT_SPAN)
    assert a.act_threshold != g.act_threshold   # both overridden, to different values
    assert a.cache_ttl_s > g.cache_ttl_s        # an app's class outlives a pointer position


def test_app_class_options_match_the_AppClass_enum():
    # The Choice option ids are parsed straight into AppClass. A mismatch would silently become
    # UNKNOWN at runtime for a category that was working a moment ago.
    from app.types import AppClass

    opts = set(load().point(PointId.A_APP_CONTEXT).questions["app_class"].options)
    assert opts == {c.value for c in AppClass}
