"""Span geometry — pure string arithmetic, which is exactly why it is NOT asked of Jev."""

import pytest

from app.text_spans import TextContext, resolve_span


def ctx(before, after):
    return TextContext(before + after, len(before), len(before), "")


def span(before, after, kind):
    c = ctx(before, after)
    r = resolve_span(c, kind)
    return c.text[r[0] : r[1]] if r else None


def test_a_url_is_selected_whole_from_a_point_inside_it():
    # The reason this point exists: pointing lands mid-URL and nobody wants half of one.
    assert span("see https://docs.type", "safe.ai/sdk for more", "url") == "https://docs.typesafe.ai/sdk"


def test_a_url_span_returns_none_where_there_is_no_url():
    # A wrong answer from Jev must fall back, not select something arbitrary.
    assert resolve_span(ctx("plain pro", "se here"), "url") is None


def test_a_quoted_string_excludes_its_quotes():
    assert span('key = "hello wo', 'rld" done', "quoted_string") == "hello world"


def test_quoted_string_handles_single_and_backtick_quotes():
    assert span("run `make c", "i` now", "quoted_string") == "make ci"
    assert span("x = 'abc", "def'", "quoted_string") == "abcdef"


def test_line_stops_at_newlines():
    assert span("a\n    return x", " + 1\nb", "line") == "    return x + 1"


def test_paragraph_stops_at_blank_lines():
    assert span("one\n\ntwo th", "ree\n\nfour", "paragraph") == "two three"


def test_sentence_stops_at_terminators():
    assert span("First one. Second o", "ne here. Third.", "sentence").strip() == "Second one here."


def test_word_includes_hyphens_and_underscores():
    # Identifiers and hyphenated words are single units to a person selecting them.
    assert span("call some_long", "_name(x)", "word") == "some_long_name"
    assert span("a well-kno", "wn thing", "word") == "well-known"


def test_word_returns_none_on_whitespace():
    assert resolve_span(ctx("a ", " b"), "word") is None


def test_offsets_are_absolute_not_window_relative():
    # The caller selects with these, against the full document. An off-by-window bug would select
    # the right length of text in the wrong place.
    c = TextContext(text="hello world", offset=6, absolute_offset=1006, word="")
    start, end = resolve_span(c, "word")
    assert (start, end) == (1006, 1011)


def test_an_unknown_span_kind_returns_none():
    assert resolve_span(ctx("a", "b"), "not_a_span") is None
