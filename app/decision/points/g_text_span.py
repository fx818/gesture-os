"""Jev point G — how much text did the user mean to select?

Pinch-dragging at character precision with a camera is miserable: the hand jitters, the frame rate
is 15fps, and a character is a few pixels. So the gesture supplies only a LOCATION, and this
decides the EXTENT — word, line, sentence, paragraph, the whole URL, the quoted string, the code
block.

That split is the same one used throughout: gesture points, Jev judges, code computes. Jev is
never asked where a URL ends — `effectors/backends/atspi_text.py` does that with a regex, exactly
and instantly. Jev is asked the one thing a regex cannot answer: which of several valid spans the
person probably wanted.

Latency shape mirrors point C: the local default (a word) is selected immediately, and the answer
refines it only if it arrives before the user acts. A 400ms wait to find out what got selected
would be worse than selecting slightly the wrong thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.decision.backends.rules import register
from app.decision.judgment_config import PointConfig
from app.decision.provider import Judgment, JudgmentRequest, Source
from app.decision.questions import PointId

POINT = PointId.G_TEXT_SPAN

SPANS = ("word", "sentence", "line", "paragraph", "code_block", "url", "quoted_string")
DEFAULT_SPAN = "word"


@dataclass(frozen=True, slots=True)
class SpanChoice:
    span: str
    confidence: float
    source: Source

    @staticmethod
    def default() -> SpanChoice:
        return SpanChoice(DEFAULT_SPAN, 0.0, Source.RULES)


def build_request(ctx, cfg: PointConfig) -> JudgmentRequest:
    """State is the text around the pointer, split so the model can see where the point IS.

    Truncated hard on both sides: the surrounding text is untrusted content — a document, a web
    page, someone else's code — and the model degrades with irrelevant context.
    """
    half = cfg.max_field_chars // 2  # tuning-exempt: split evenly either side of the point
    return JudgmentRequest(
        point=POINT,
        state={
            "text_before_the_point": ctx.before[-half:],
            "text_after_the_point": ctx.after[:half],
        },
        questions=cfg.questions,
        # Keyed on the immediate neighbourhood: pointing at the same place twice should not pay
        # twice, but moving to a different word should re-ask.
        cache_key=_cache_key(ctx, cfg),
        rev=cfg.rev,
    )


def _cache_key(ctx, cfg: PointConfig) -> str:
    n = int(cfg.fallback.value("cache_neighbourhood_chars"))
    return f"{ctx.before[-n:]}|{ctx.after[:n]}|r{cfg.rev}"


def interpret(answers: Mapping[str, Judgment], cfg: PointConfig) -> SpanChoice:
    judgment = answers.get("span")
    if judgment is None:
        return SpanChoice.default()
    span = str(judgment.value)
    if span not in SPANS:
        # Outside the closed set should be impossible; degrading to `word` is the only safe
        # reading, since selecting the wrong extent is a visible, correctable mistake.
        return SpanChoice.default()
    return SpanChoice(span, judgment.confidence, judgment.source)


# --------------------------------------------------------------------------------------
# Offline rules fallback
# --------------------------------------------------------------------------------------


@register(POINT)
def fallback(req: JudgmentRequest) -> Mapping[str, Judgment]:
    """Structural cues only — the ones a regex can genuinely see.

    Deliberately limited to the unambiguous cases: sitting inside a URL or inside quotes is a fact
    about the text, not a judgment. Everything else defaults to `word`, which is the safest
    possible wrong answer because extending a selection is easy and undoing one is annoying.
    """
    from app.decision.judgment_config import load as _load_judgment
    from app.text_spans import _QUOTED, _URL

    fb = _load_judgment().point(POINT).fallback
    before = str(req.state.get("text_before_the_point", ""))
    after = str(req.state.get("text_after_the_point", ""))
    text = before + after
    i = len(before)

    span, confidence = DEFAULT_SPAN, fb.value("default_confidence")
    for pattern, name in ((_URL, "url"), (_QUOTED, "quoted_string")):
        for m in pattern.finditer(text):
            if m.start() <= i <= m.end():
                span, confidence = name, fb.value("structural_confidence")
                break
        if span != DEFAULT_SPAN:
            break

    return {"span": Judgment("span", span, confidence, Source.RULES)}
