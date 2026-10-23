"""Cache keys for focus. Stability is the requirement — a key that changes on every keystroke
means a 375ms round trip per document."""

from app.naming import cache_key, normalize_title, same_target
from app.types import FocusInfo


def _f(app, title):
    return FocusInfo(app, title, "frame", None, 0.0)


def test_leading_status_glyphs_are_stripped():
    # VS Code prefixes a modified marker and ptyxis a spinner; both change while you type.
    assert normalize_title("✳ foo - bar") == normalize_title("foo - bar")
    assert normalize_title("◐ gesture-os — claude", app_name="ptyxis") == "gesture-os"


def test_notification_badges_are_stripped():
    assert normalize_title("(3) Inbox - Gmail - Google Chrome") == "inbox - gmail"


def test_application_name_suffix_chains_are_stripped():
    assert normalize_title(
        "x - bl-auditor-project - Visual Studio Code", app_name="code"
    ) == "x - bl-auditor-project"


def test_different_content_stays_distinct():
    # The dangerous direction is over-collapsing: for a browser the page genuinely can change the
    # answer, so two pages must not share a cached classification.
    a = normalize_title("Usage - Google Chrome", app_name="Google Chrome")
    b = normalize_title("Google Sheets - Google Chrome", app_name="Google Chrome")
    assert a != b


def test_rev_participates_in_the_cache_key():
    # Editing a prompt must invalidate its own cache. Without this a reworded question appears to
    # do nothing until the TTL expires — the most confusing failure a cached model call has.
    f = _f("code", "x")
    assert cache_key(f, rev=1) != cache_key(f, rev=2)


def test_the_same_window_produces_the_same_key_across_calls():
    f = _f("code", "✳ engine.py - gesture-os - Visual Studio Code")
    assert cache_key(f, rev=1) == cache_key(f, rev=1)


def test_a_title_changing_only_by_its_modified_marker_hits_the_same_key():
    saved = _f("code", "engine.py - gesture-os - Visual Studio Code")
    dirty = _f("code", "✳ engine.py - gesture-os - Visual Studio Code")
    assert cache_key(saved, rev=1) == cache_key(dirty, rev=1)


def test_same_target_suppresses_redundant_activations():
    # AT-SPI emits window:activate more than once for the same window.
    a = _f("code", "✳ x - Visual Studio Code")
    b = _f("code", "x - Visual Studio Code")
    assert same_target(a, b)
    assert not same_target(a, _f("ptyxis", "x"))
    assert not same_target(a, None)


def test_empty_title_is_handled():
    assert normalize_title("") == ""
    assert cache_key(_f("Google Chrome", ""), rev=1).startswith("google chrome|")
