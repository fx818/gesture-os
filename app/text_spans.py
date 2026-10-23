"""Text span geometry — pure string arithmetic, no AT-SPI, no I/O.

Separated from `effectors/backends/atspi_text.py` so it sits BELOW both `decision` and
`effectors`, which are sibling layers and may not import each other. Jev point G's rules fallback
needs these patterns and the decision layer cannot reach into effectors to get them.

It is the right split regardless: deciding where a URL ends is deterministic, and keeping it
away from the accessibility plumbing makes it testable without a desktop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Span extents that AT-SPI cannot express as a boundary type. Computed here, in code.
_URL = re.compile(r"""[a-z][a-z0-9+.-]*://[^\s<>"')\]]+|www\.[^\s<>"')\]]+""", re.I)
_QUOTED = re.compile(r"""(["'`])((?:\\.|(?!\1).)*)\1""")
_CODE_FENCE = re.compile(r"```[\s\S]*?```")

# How much text around the caret to read. Enough for a paragraph or a code block, small enough to
# stay well inside the state budget and not bury Jev in irrelevant context.
CONTEXT_CHARS = 600


@dataclass(frozen=True, slots=True)
class TextContext:
    """What the user is pointing at, and enough around it to judge the span."""

    text: str
    offset: int          # caret/pointer position WITHIN `text`
    absolute_offset: int  # the same position in the full document
    word: str

    @property
    def before(self) -> str:
        return self.text[: self.offset]

    @property
    def after(self) -> str:
        return self.text[self.offset :]




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
