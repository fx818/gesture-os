"""Universal undo. The scope doc asks for one gesture that reverses the last action "regardless of
which mode produced it" — which only works if the inverse is recorded at the time."""

from app.intents import Direction, KeyChord, MoveCursor, SendToMonitor, SendToWorkspace, ShowDesktop, TileWindow, Undo, Zone
from app.routing.journal import ActionJournal, inverse


def test_directional_commands_invert_to_their_opposite():
    assert inverse(SendToWorkspace(Direction.LEFT)) == SendToWorkspace(Direction.RIGHT)
    assert inverse(SendToMonitor(Direction.UP)) == SendToMonitor(Direction.DOWN)


def test_show_desktop_is_its_own_inverse():
    assert inverse(ShowDesktop()) == ShowDesktop()


def test_cursor_motion_has_no_meaningful_inverse():
    # Moving the mouse back is not "undo" — it is another mouse move. Recording it would let a
    # single Undo gesture consume a cursor jiggle instead of reversing the command the user meant.
    assert inverse(MoveCursor(3.0, 4.0)) is None


def test_arbitrary_tiling_is_honestly_not_undoable_yet():
    # Restoring a window's previous rectangle needs geometry only the Shell extension can report.
    # Returning None is better than a plausible-looking wrong inverse.
    assert inverse(TileWindow(Zone.MAIN)) is None


def test_a_macro_defers_to_the_applications_own_undo():
    assert inverse(KeyChord(("super", "left"))) == KeyChord(("ctrl", "z"))
    # ...and undo does not recurse into itself.
    assert inverse(KeyChord(("ctrl", "z"))) is None


def test_undo_resolves_to_the_last_reversible_action():
    j = ActionJournal()
    j.record(0.0, SendToWorkspace(Direction.LEFT))
    assert j.expand([Undo()]) == [SendToWorkspace(Direction.RIGHT)]


def test_undo_with_nothing_to_undo_disappears_quietly():
    # An Undo that resolves to nothing must not reach the router as an unroutable intent.
    assert ActionJournal().expand([Undo()]) == []


def test_unreversible_actions_are_not_journalled():
    j = ActionJournal()
    assert j.record(0.0, MoveCursor(1.0, 1.0)) is False
    assert len(j) == 0


def test_undo_unwinds_in_reverse_order():
    j = ActionJournal()
    j.record(0.0, SendToWorkspace(Direction.LEFT))
    j.record(1.0, SendToMonitor(Direction.LEFT))
    assert j.expand([Undo()]) == [SendToMonitor(Direction.RIGHT)]
    assert j.expand([Undo()]) == [SendToWorkspace(Direction.RIGHT)]


def test_journal_is_bounded():
    j = ActionJournal(limit=3)
    for i in range(10):
        j.record(float(i), SendToWorkspace(Direction.LEFT))
    assert len(j) == 3
