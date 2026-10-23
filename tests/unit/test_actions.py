"""The action catalogue — the closed set that makes invalid bindings structurally impossible."""

import pytest

from app.actions import ANY, ActionCatalogue, ActionSpec, load


def test_the_shipped_catalogue_loads():
    assert len(load()) >= 10


def test_options_with_no_context_offers_everything():
    # Point E needs this: the user is choosing what a gesture DOES, and the context is a separate
    # question. Filtering here would make 'next slide' impossible to bind at all.
    catalogue = load()
    assert len(catalogue.options(app_class=None)) == len(catalogue)
    assert "next_slide" in catalogue.options(app_class=None)


def test_options_for_a_context_narrow_to_what_is_usable():
    # Point C needs this: scoring actions that cannot apply wastes tokens and invites a confident
    # wrong answer that a filter makes impossible.
    assert "next_slide" not in load().options("terminal")
    assert "next_slide" in load().options("presentation")


def test_universal_actions_are_offered_everywhere():
    for context in ("terminal", "browser", "presentation", "unknown"):
        assert "maximize" in load().options(context), context


def test_every_action_has_a_description_written_for_a_stranger():
    # The description IS the option's meaning as far as Jev is concerned, so what this guards is a
    # blank, a bare label, or a fragment — not an arbitrary length. A full sentence of several
    # words is the bar.
    for spec in load().actions.values():
        assert spec.description[0].isupper() and spec.description.endswith("."), spec.id
        assert len(spec.description.split()) >= 5, f"{spec.id}: too terse for an option"
        assert spec.description.lower() != f"{spec.label.lower()}.", f"{spec.id}: restates the label"


def test_a_description_free_action_is_rejected(tmp_path):
    path = tmp_path / "actions.yaml"
    path.write_text("actions:\n  a: {label: A}\n  b: {label: B, description: Fine.}\n")
    with pytest.raises(ValueError, match="no description"):
        load(path)


def test_a_catalogue_too_small_to_form_a_choice_is_rejected(tmp_path):
    path = tmp_path / "actions.yaml"
    path.write_text("actions:\n  only: {label: O, description: The only one.}\n")
    with pytest.raises(ValueError, match="at least two"):
        load(path)


def test_available_in_respects_any():
    spec = ActionSpec("x", "X", "desc", (ANY,))
    assert spec.available_in("terminal") and spec.available_in("anything")
    narrow = ActionSpec("y", "Y", "desc", ("browser",))
    assert narrow.available_in("browser") and not narrow.available_in("terminal")
