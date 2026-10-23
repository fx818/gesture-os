"""Zone -> rectangle.

Jev point B answers *which* zone a window belongs in. This turns that into geometry, in code,
because it is arithmetic over the monitor work area and the model is documented as bad at exactly
that — and because the split ratios are tuning constants a user will want to change.

The work area, not the monitor rect: placing by raw monitor geometry puts the titlebar under the
GNOME top bar.
"""

from __future__ import annotations

from app.intents import Zone
from app.types import LayoutSnapshot, Rect

# Fraction of the work area the main zone occupies horizontally. The remainder is the side panel.
MAIN_FRACTION = 0.62  # tuning-exempt: layout ratio, moves to config when the HUD can edit it
BACKGROUND_FRACTION = 0.38


def resolve(zone: Zone, layout: LayoutSnapshot | None, monitor: int = 0) -> Rect | None:
    """The rectangle for `zone` on `monitor`, or None when the layout is unknown."""
    if layout is None or not layout.monitors:
        return None
    area = next(
        (m.rect for m in layout.monitors if m.index == monitor),
        layout.monitors[0].rect,
    )

    main_w = int(area.width * MAIN_FRACTION)
    side_w = area.width - main_w
    bg_h = int(area.height * BACKGROUND_FRACTION)

    match zone:
        case Zone.MAIN:
            return Rect(area.x, area.y, main_w, area.height)
        case Zone.SIDE_PANEL:
            return Rect(area.x + main_w, area.y, side_w, area.height)
        case Zone.BACKGROUND:
            # Bottom of the side column: visible enough to glance at, small enough to ignore.
            return Rect(area.x + main_w, area.y + area.height - bg_h, side_w, bg_h)
        case Zone.LEFT_HALF:
            return Rect(area.x, area.y, area.width // 2, area.height)
        case Zone.RIGHT_HALF:
            return Rect(area.x + area.width // 2, area.y, area.width // 2, area.height)
        case Zone.MAXIMIZE:
            return area
        case _:
            return None
