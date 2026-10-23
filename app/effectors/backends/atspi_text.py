"""Reading and selecting text through AT-SPI. The other half of Jev point G.

The division of labour is the same one used everywhere else in this project: the **gesture**
supplies a location, **Jev** supplies the kind of span the user probably means, and **code**
computes the actual character range. Jev is never asked where a URL ends — that is arithmetic over
a string, which it is documented to be bad at and which a regex does perfectly.

`get_offset_at_point` is what makes pointing at text viable at all: it turns a screen coordinate
straight into a text offset, so ray-cast pointing does not need to reason about fonts or layout.

Only this module and `atspi_focus.py` may import gi (enforced by .importlinter).
"""

from __future__ import annotations

from app.types import Capability

_CAPS = frozenset({Capability.UI_TREE_READ})

from app.text_spans import CONTEXT_CHARS, TextContext, resolve_span  # noqa: F401

class AtspiTextSource:
    def __init__(self) -> None:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        self._atspi = Atspi
        Atspi.init()

    def capabilities(self) -> frozenset[Capability]:
        return _CAPS

    def close(self) -> None:
        return None

    # -- reading -------------------------------------------------------------------

    def _focused_text(self):
        """The focused accessible that implements Text, or None."""
        A = self._atspi
        try:
            desktop = A.get_desktop(0)
        except Exception:
            return None
        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                for j in range(app.get_child_count()):
                    win = app.get_child_at_index(j)
                    if not win.get_state_set().contains(A.StateType.ACTIVE):
                        continue
                    found = self._find_text_descendant(win)
                    if found is not None:
                        return found
            except Exception:
                continue
        return None

    def _find_text_descendant(self, node, depth: int = 0):
        # Bounded: an accessibility tree can be enormous, and a focused text field is near the
        # focused node, not buried twenty levels down.
        if depth > 6:  # tuning-exempt: tree search depth
            return None
        try:
            if node.get_state_set().contains(self._atspi.StateType.FOCUSED):
                if node.get_text_iface() is not None:
                    return node
            for k in range(min(node.get_child_count(), 40)):  # tuning-exempt: fan-out cap
                found = self._find_text_descendant(node.get_child_at_index(k), depth + 1)
                if found is not None:
                    return found
        except Exception:
            return None
        return None

    def context_at_caret(self, max_chars: int = CONTEXT_CHARS) -> TextContext | None:
        node = self._focused_text()
        if node is None:
            return None
        try:
            iface = node.get_text_iface()
            total = iface.get_character_count()
            caret = iface.get_caret_offset()
            start = max(0, caret - max_chars // 2)
            end = min(total, caret + max_chars // 2)
            text = iface.get_text(start, end)
            word = iface.get_string_at_offset(
                caret, self._atspi.TextGranularity.WORD
            ).content if hasattr(self._atspi, "TextGranularity") else ""
            return TextContext(
                text=text, offset=caret - start, absolute_offset=caret, word=word or ""
            )
        except Exception:
            return None

    def context_at_point(self, x: int, y: int, max_chars: int = CONTEXT_CHARS) -> TextContext | None:
        """Text around a SCREEN POINT — what ray-cast pointing needs."""
        node = self._focused_text()
        if node is None:
            return None
        try:
            iface = node.get_text_iface()
            offset = iface.get_offset_at_point(x, y, self._atspi.CoordType.SCREEN)
            if offset < 0:
                return None
            total = iface.get_character_count()
            start = max(0, offset - max_chars // 2)
            end = min(total, offset + max_chars // 2)
            return TextContext(
                text=iface.get_text(start, end),
                offset=offset - start,
                absolute_offset=offset,
                word="",
            )
        except Exception:
            return None

    def select(self, start: int, end: int) -> bool:
        node = self._focused_text()
        if node is None:
            return False
        try:
            iface = node.get_text_iface()
            if iface.get_n_selections() > 0:
                iface.remove_selection(0)
            return bool(iface.add_selection(start, end))
        except Exception:
            return False


# --------------------------------------------------------------------------------------
# Span extents — computed in code, because this is string arithmetic
# --------------------------------------------------------------------------------------


def resolve_span(ctx: TextContext, span: str) -> tuple[int, int] | None:
    """(start, end) ABSOLUTE offsets for the chosen span kind, or None if it does not apply.

    Jev chose `span`; everything below is deterministic. Returning None when a span does not
    actually exist at that point matters — a 'url' answer where there is no URL must fall back
    rather than select something arbitrary.
    """
    text, i = ctx.text, ctx.offset
    base = ctx.absolute_offset - i

    def abs_range(a: int, b: int) -> tuple[int, int]:
        return base + a, base + b

    if span == "url":
        for m in _URL.finditer(text):
            if m.start() <= i <= m.end():
                return abs_range(m.start(), m.end())
        return None
    if span == "quoted_string":
        for m in _QUOTED.finditer(text):
            if m.start() <= i <= m.end():
                return abs_range(m.start() + 1, m.end() - 1)
        return None
    if span == "code_block":
        for m in _CODE_FENCE.finditer(text):
            if m.start() <= i <= m.end():
                return abs_range(m.start(), m.end())
        return None
    if span == "line":
        a = text.rfind("\n", 0, i) + 1
        b = text.find("\n", i)
        return abs_range(a, len(text) if b < 0 else b)
    if span == "paragraph":
        a = text.rfind("\n\n", 0, i)
        a = 0 if a < 0 else a + 2
        b = text.find("\n\n", i)
        return abs_range(a, len(text) if b < 0 else b)
    if span == "sentence":
        starts = [m.end() for m in re.finditer(r"[.!?]\s+", text[:i])]
        a = starts[-1] if starts else 0
        m = re.search(r"[.!?](\s|$)", text[i:])
        b = i + m.end() if m else len(text)
        return abs_range(a, b)
    if span == "word":
        a = i
        while a > 0 and (text[a - 1].isalnum() or text[a - 1] in "_-"):
            a -= 1
        b = i
        while b < len(text) and (text[b].isalnum() or text[b] in "_-"):
            b += 1
        return abs_range(a, b) if b > a else None
    return None
