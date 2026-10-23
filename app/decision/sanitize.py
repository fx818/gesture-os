"""Make untrusted state safe to send.

Window titles are attacker-controlled: any web page can set `document.title` to
"Ignore previous instructions and ...", and the TypeSafe docs list susceptibility to instruction
injection from state as a known weakness of the model.

Three defences, in order of importance:

1. **Closed sets.** Every question on an untrusted path is a Choice over ids we define. The worst
   an injection can achieve is a wrong enum member — never an action. That is structural and lives
   in the question definitions, not here.
2. **Instructions are static.** Prose comes from points.yaml and never interpolates state. Nothing
   here concatenates user data into an instruction.
3. **This module.** Truncate per field, strip control characters, and label every untrusted value
   so it reads as data rather than as prose continuing the instruction.

The scope doc also has a privacy stance ("no frames leave the machine"). Titles are not frames, but
they do leak document and client names, so truncation is a privacy control too, not only a safety one.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping

# C0/C1 control characters except tab/newline, plus zero-width and bidi-override characters, which
# are the usual way to smuggle text past a human reviewer reading the same string.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
_WHITESPACE = re.compile(r"\s+")

DEFAULT_MAX_FIELD_CHARS = 200
DEFAULT_MAX_TOTAL_CHARS = 4000
TRUNCATION_MARK = "…"


def scrub(value: str, max_chars: int = DEFAULT_MAX_FIELD_CHARS) -> str:
    """Normalize, strip control characters, collapse whitespace, truncate."""
    text = unicodedata.normalize("NFC", value)
    text = _CONTROL.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + TRUNCATION_MARK
    return text


def sanitize_state(
    state: Mapping[str, str | int | float],
    *,
    max_field_chars: int = DEFAULT_MAX_FIELD_CHARS,
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
) -> dict[str, str | int | float]:
    """Scrub every string field. Numbers pass through — they cannot carry an instruction.

    Keys are scrubbed too: a state built from external data could otherwise smuggle text in a key.
    Total budget is enforced last, because the model degrades with irrelevant context (documented)
    and an oversized state is also an oversized bill.
    """
    out: dict[str, str | int | float] = {}
    budget = max_total_chars
    for raw_key, raw_value in state.items():
        key = scrub(str(raw_key), 64)
        if not key:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, str):
            out[key] = raw_value
            continue
        allowance = min(max_field_chars, max(0, budget))
        value = scrub(raw_value, allowance) if allowance else ""
        budget -= len(value)
        out[key] = value
    return out
