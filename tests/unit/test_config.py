"""The config loader's validation is a safety mechanism, not input hygiene.

Every assertion here corresponds to a real failure mode the scope doc calls out: mode flicker at
thresholds, and false positives from a badly calibrated profile. A config that could produce those
must fail at startup, not in the user's hand.
"""

import pytest

from app.config import Config, ConfigError, load
from app.types import ModeId


def test_default_config_loads_and_validates():
    cfg = load(use_env=False)
    assert isinstance(cfg, Config)
    # 550ms, not the scope doc's 250ms — the window's real unit is frames of evidence and
    # this camera runs at 15fps. See ADR-0009.
    assert cfg.arbitration.window_span_ms == 550.0


def test_every_mode_has_a_schmitt_pair_with_sustain_below_enter():
    # Hysteresis layer 1. If sustain >= enter for any mode, that mode can oscillate at its
    # boundary — the exact "flickering at the boundaries" the scope doc designs against.
    cfg = load(use_env=False)
    for mode in ModeId:
        assert cfg.arbitration.sustain[mode] < cfg.arbitration.enter[mode], mode


def test_inverted_schmitt_pair_is_rejected_at_load():
    with pytest.raises(ConfigError, match="must be <"):
        load(use_env=False, overrides={"arbitration": {"sustain": {"precision": 0.99}}})


def test_equal_schmitt_pair_is_rejected():
    # Equality is the subtle case: it looks harmless and flutters just as badly.
    with pytest.raises(ConfigError):
        load(use_env=False, overrides={"arbitration": {"sustain": {"gross": 0.80}}})


def test_gross_speed_pair_must_also_be_a_schmitt_pair():
    # A hand parked at the gross threshold must not be able to oscillate in and out of a
    # window-manager command — that is the most destructive misfire available.
    with pytest.raises(ConfigError, match="speed_sustain"):
        load(use_env=False, overrides={"gross": {"speed_sustain": 2.0}})


def test_pinch_click_thresholds_must_not_invert():
    # Single-threshold pinch detection chatters, producing double-clicks on a held pinch.
    with pytest.raises(ConfigError, match="chatters"):
        load(use_env=False, overrides={"precision": {"pinch": {"click_open": 0.1}}})


def test_zero_enter_frames_is_rejected():
    # enter_frames == 0 disables the streak requirement (hysteresis layer 2) entirely.
    with pytest.raises(ConfigError, match="enter_frames"):
        load(use_env=False, overrides={"arbitration": {"enter_frames": {"macro": 0}}})


def test_window_needs_at_least_two_frames_for_velocity():
    with pytest.raises(ConfigError, match="two samples"):
        load(use_env=False, overrides={"window": {"min_frames": 1}})


def test_missing_mode_in_a_threshold_table_is_rejected():
    # Adding a ModeId without adding its thresholds would otherwise KeyError deep inside a guard
    # at runtime. _build is the real gate, so test it directly rather than through the merge
    # (merging a partial table leaves the defaults in place and tests nothing).
    import tomllib

    from app.config import DEFAULT_CONFIG, _build

    with DEFAULT_CONFIG.open("rb") as fh:
        raw = tomllib.load(fh)
    del raw["arbitration"]["enter"]["panic"]
    with pytest.raises(ConfigError, match="missing mode 'panic'"):
        _build(raw)


def test_env_overrides_use_double_underscore_as_section_separator(monkeypatch):
    # Single underscore has to survive inside key names (min_cutoff, max_palm_speed).
    monkeypatch.setenv("GESTURE_OS_GROSS__SPEED", "2.5")
    cfg = load()
    assert cfg.gross.speed == 2.5


def test_env_flags_are_not_mistaken_for_config_keys(monkeypatch):
    # GESTURE_OS_OFFLINE is a flag with no section; it must not corrupt the config tree.
    monkeypatch.setenv("GESTURE_OS_OFFLINE", "1")
    cfg = load()
    assert cfg.gross.speed == 1.8


def test_config_is_frozen():
    cfg = load(use_env=False)
    with pytest.raises(Exception):
        cfg.gross = None
