"""Zone geometry. Arithmetic kept in code because Jev cannot do it and because these ratios are
tuning a user will want to change."""

from app.intents import Zone
from app.routing.zones import resolve
from app.types import LayoutSnapshot, MonitorInfo, Rect

# Work area, not monitor rect: 32px of top bar already removed.
AREA = Rect(0, 32, 1920, 1048)
LAYOUT = LayoutSnapshot(monitors=(MonitorInfo(0, AREA, True),), windows=(), t_ms=0.0)


def test_zones_never_overlap_the_top_bar():
    # Placing by the raw monitor rect puts the titlebar under the GNOME panel.
    for zone in (Zone.MAIN, Zone.SIDE_PANEL, Zone.BACKGROUND, Zone.MAXIMIZE):
        rect = resolve(zone, LAYOUT)
        assert rect.y >= AREA.y, zone


def test_main_and_side_panel_tile_the_work_area_exactly():
    # A one-pixel gap or overlap is visible, and compounds as windows are re-tiled.
    main = resolve(Zone.MAIN, LAYOUT)
    side = resolve(Zone.SIDE_PANEL, LAYOUT)
    assert main.x == AREA.x
    assert main.x + main.width == side.x
    assert side.x + side.width == AREA.x + AREA.width


def test_main_is_the_larger_share():
    assert resolve(Zone.MAIN, LAYOUT).width > resolve(Zone.SIDE_PANEL, LAYOUT).width


def test_background_sits_under_the_side_panel_not_over_main():
    bg = resolve(Zone.BACKGROUND, LAYOUT)
    main = resolve(Zone.MAIN, LAYOUT)
    assert bg.x >= main.x + main.width
    assert bg.y + bg.height == AREA.y + AREA.height


def test_halves_tile_exactly():
    left = resolve(Zone.LEFT_HALF, LAYOUT)
    right = resolve(Zone.RIGHT_HALF, LAYOUT)
    assert left.x + left.width == right.x
    assert right.x + right.width == AREA.x + AREA.width


def test_maximize_is_the_whole_work_area():
    assert resolve(Zone.MAXIMIZE, LAYOUT) == AREA


def test_no_layout_means_no_guess():
    # Better to report the intent unsupported than to place a window at coordinates invented from
    # nothing.
    assert resolve(Zone.MAIN, None) is None


def test_a_second_monitor_is_honoured():
    second = Rect(1920, 0, 2560, 1440)
    layout = LayoutSnapshot(
        monitors=(MonitorInfo(0, AREA, True), MonitorInfo(1, second, False)), windows=(), t_ms=0.0
    )
    rect = resolve(Zone.MAIN, layout, monitor=1)
    assert rect.x == second.x and rect.height == second.height
