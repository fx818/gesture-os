"""Focus identity and cache keys — pure string normalization over a FocusInfo.

Lives at the bottom of the stack, beside `intents` and `config`, because BOTH `decision`
(which keys its cache on a window) and `effectors` (whose AT-SPI watcher suppresses duplicate
activations) need it. `context/` is the layer ABOVE decision that holds DecisionContext
snapshots, so putting these there made decision import upward — caught by import-linter.


Window titles are volatile — they change on every keystroke in an editor and every tab switch in a
browser. Sending the raw title is right (it is evidence), but *keying the cache* on it would mean a
fresh 375 ms round trip for every document the user opens.

`normalize_title` strips the volatile decoration so that "◐ foo — claude" and "✳ bar — claude"
collapse to the same key, while genuinely different content ("Google Sheets" vs "Usage") stays
distinct — because for a browser the content really can change the answer.
"""

from __future__ import annotations

import re

from app.types import FocusInfo

# Leading status glyphs: modified markers, spinners, unread dots.
_LEADING_GLYPHS = re.compile(r"^[\s✳◐◑◒◓●○•*▲△◆◇★☆⬤]+")
# Notification badges: "(3) Inbox", "[2] Slack"
_BADGE = re.compile(r"^[\(\[]\d+[\)\]]\s*")
# Trailing " - App Name" / " — App Name" chains, repeated. Chrome produces three of them.
_SUFFIX_CHAIN = re.compile(r"\s*[-—–]\s*[^-—–]{1,40}$")
_WHITESPACE = re.compile(r"\s+")

# Suffixes worth stripping repeatedly: application names and the user's own name, which GNOME and
# Chrome append to profile windows.
_STRIPPABLE_SUFFIXES = (
    "google chrome", "chromium", "brave", "firefox", "mozilla firefox",
    "visual studio code", "vscode", "code",
    "claude", "ptyxis", "gnome terminal", "konsole", "kitty", "alacritty",
    "vlc media player", "libreoffice impress", "libreoffice writer", "libreoffice calc",
    "mozilla thunderbird", "nautilus", "files",
)

MAX_KEY_CHARS = 80


def normalize_title(
    title: str, *, app_name: str = "", max_chars: int = MAX_KEY_CHARS
) -> str:
    """Collapse a title to a stable cache signature. Lowercased; never sent to Jev.

    Deliberately conservative. Over-collapsing is the dangerous direction: for a browser the
    content genuinely can change the answer (a Google Sheets tab is arguably a document editor),
    so two different pages must not share a cached classification. Anything left behind — a Chrome
    profile suffix like " - anurag", say — is harmless, because it is *stable*, and stability is
    the whole requirement.
    """
    text = _LEADING_GLYPHS.sub("", title or "")
    text = _BADGE.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()

    # Strip known application-name suffixes, repeatedly — Chrome appends up to three.
    for _ in range(4):
        m = _SUFFIX_CHAIN.search(text)
        if not m:
            break
        tail = m.group(0).lstrip(" -—–").strip().lower()
        app = app_name.strip().lower()
        if app and (tail == app or tail.endswith(app)):
            text = text[: m.start()].rstrip()
            continue
        if tail in _STRIPPABLE_SUFFIXES or tail.endswith(_STRIPPABLE_SUFFIXES):
            text = text[: m.start()].rstrip()
            continue
        break

    return text.lower()[:max_chars].strip()


def cache_key(focus: FocusInfo, *, rev: int) -> str:
    """Key for a point-A judgment.

    `rev` comes from config/judgment/points.yaml and is bumped whenever the prompt is edited, so
    a reworded question invalidates its own cache automatically. Without this, a prompt change
    would appear to do nothing until the cache expired — the single most confusing failure mode
    a cached LLM call has.
    """
    return (
        f"{focus.app_name.strip().lower()}"
        f"|{normalize_title(focus.window_title, app_name=focus.app_name)}"
        f"|r{rev}"
    )


def same_target(a: FocusInfo | None, b: FocusInfo | None) -> bool:
    """AT-SPI emits window:activate redundantly; this suppresses the duplicates."""
    if a is None or b is None:
        return a is b
    return a.app_name == b.app_name and normalize_title(
        a.window_title, app_name=a.app_name
    ) == normalize_title(b.window_title, app_name=b.app_name)
