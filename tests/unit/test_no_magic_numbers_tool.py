"""The magic-number lint is a guard rail; a guard rail that doesn't catch anything is worse than
none, because it implies coverage that isn't there. So test what it catches and what it allows."""

import textwrap

from tools.check_no_magic_numbers import check_file


def _check(tmp_path, src):
    p = tmp_path / "m.py"
    p.write_text(textwrap.dedent(src))
    return check_file(p)


def test_catches_a_threshold_hidden_in_a_comparison(tmp_path):
    # The exact failure it exists to prevent: a velocity gate that calibration cannot reach.
    out = _check(tmp_path, "def guard(f):\n    return f.palm_speed > 1.8\n")
    assert len(out) == 1 and "1.8" in out[0]


def test_catches_a_dwell_window(tmp_path):
    out = _check(tmp_path, "def held(t):\n    return t > 450\n")
    assert len(out) == 1 and "450" in out[0]


def test_allows_identity_and_index_constants(tmp_path):
    # 0, 1 and -1 are structure, not tuning: empty checks, first/last index, sign flips.
    assert _check(tmp_path, """
        def f(xs, cfg):
            if not xs:
                return 0
            first, last = xs[0], xs[-1]
            return first * 1 + last * -1
    """) == []


def test_allows_values_read_from_config(tmp_path):
    assert _check(tmp_path, """
        def guard(f, cfg):
            return f.palm_speed > cfg.gross.speed
    """) == []


def test_booleans_are_not_numbers(tmp_path):
    # dataclass(frozen=True, slots=True) appears constantly; bool is an int subclass in Python,
    # so this is an easy false positive to ship by accident.
    assert _check(tmp_path, """
        from dataclasses import dataclass
        @dataclass(frozen=True, slots=True)
        class S:
            ok: bool = True
    """) == []


def test_strings_and_docstrings_are_not_numbers(tmp_path):
    assert _check(tmp_path, '''
        """Module docstring mentioning 250ms."""
        NAME = "gross.speed"
    ''') == []


def test_negative_literal_is_reported_with_its_sign(tmp_path):
    out = _check(tmp_path, "X = -0.5\n")
    assert len(out) == 1 and "-0.5" in out[0]


def test_reports_line_numbers(tmp_path):
    out = _check(tmp_path, "a = 1\nb = 2\nc = 1\nd = 3\n")
    assert [o.split(":")[1] for o in out] == ["2", "4"]


def test_tuning_exempt_pragma_requires_a_reason_and_silences_that_line(tmp_path):
    # Escape hatch for numbers that genuinely are not thresholds — a cache size, a rounding
    # precision. It is deliberately per-line and deliberately requires a written reason, so the
    # exemption shows up in review instead of being a silent hole in the rule.
    assert _check(tmp_path, """
        from functools import lru_cache
        @lru_cache(maxsize=32)  # tuning-exempt: cache size, not a threshold
        def f(x):
            return round(x * 0.5, 3)  # tuning-exempt: rounding precision
    """) == []


def test_the_pragma_only_exempts_its_own_line(tmp_path):
    out = _check(tmp_path, """
        A = 32  # tuning-exempt: fine
        B = 1.8
    """)
    assert len(out) == 1 and "1.8" in out[0]
