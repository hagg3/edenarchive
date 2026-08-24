"""Per-row flags, per-origin session stats, and the explainable quality score.

Eleven orthogonal boolean flags per row, packed into one bitmask column so
filters can combine them with fast integer ops in SQL. Junk is scored and
toggleable, never dropped at index time — see the project plan for why the
three prior triage scripts in this directory got this wrong.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable, Optional

from . import terms

FLAG_NAMES = [
    "f_empty",
    "f_default",
    "f_chat_channel",
    "f_chat_words",
    "f_chat_escape",
    "f_repost",
    "f_burst",
    "f_flood",
    "f_gibberish",
    "f_short",
    "f_featured",
]
FLAG_BITS = {name: i for i, name in enumerate(FLAG_NAMES)}
JUNK_FLAG_NAMES = [f for f in FLAG_NAMES if f != "f_featured"]


def flags_mask(**kwargs: bool) -> int:
    mask = 0
    for name, val in kwargs.items():
        if val:
            mask |= 1 << FLAG_BITS[name]
    return mask


def flags_list(mask: int) -> list[str]:
    return [name for name, bit in FLAG_BITS.items() if mask & (1 << bit)]


# ---------------------------------------------------------------------------
# Per-name flags — pure functions of the name string.
# ---------------------------------------------------------------------------

_DEFAULT_NAME_RE = re.compile(r"^world\s*\d+$", re.IGNORECASE)


def is_default_name(name: str) -> bool:
    return bool(_DEFAULT_NAME_RE.match(name.strip()))


# Handle'CHANNEL'message and punctuation-escape tokens share the same
# 'xxx' quoting convention — which one it is depends on the token's meaning.
_QUOTED_TOKEN_RE = re.compile(r"'([a-z]{2,8})'", re.IGNORECASE)


def detect_chat_channel(name: str) -> Optional[str]:
    for m in _QUOTED_TOKEN_RE.finditer(name):
        tag = m.group(1).lower()
        if tag in terms.CHAT_CHANNEL_TAGS:
            return tag
    return None


def detect_chat_escape(name: str) -> bool:
    for m in _QUOTED_TOKEN_RE.finditer(name):
        tag = m.group(1).lower()
        if tag in terms.CHAT_ESCAPE_TOKENS and tag not in terms.CHAT_CHANNEL_TAGS:
            return True
    return False


_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def detect_chat_words(name: str) -> bool:
    tokens = [t.lower() for t in _WORD_RE.findall(name)]
    hits = sum(1 for t in tokens if t in terms.CHAT_WORDS)
    return hits >= 2


_VOWEL_RE = re.compile(r"[aeiou]")


def detect_gibberish(name: str) -> bool:
    """Keyboard-mash / random-token names: a single long word with an
    implausibly low vowel ratio. Multi-word names are excluded — mashing a
    keyboard rarely produces clean word boundaries."""
    if " " in name.strip():
        return False
    stripped = re.sub(r"[^a-z]", "", name.lower())
    if len(stripped) < 6:
        return False
    ratio = len(_VOWEL_RE.findall(stripped)) / len(stripped)
    return ratio < 0.15


def detect_short(name: str) -> bool:
    s = name.strip()
    return 0 < len(s) <= 2


_AUTHOR_RE = re.compile(r"\bby\s+([A-Za-z0-9][A-Za-z0-9 ']{0,30})$", re.IGNORECASE)


def extract_author(name: str) -> Optional[str]:
    m = _AUTHOR_RE.search(name)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Corpus-wide flags — need the full row set, computed in one pass by index.py.
# ---------------------------------------------------------------------------

BURST_MIN_COUNT = 5
BURST_WINDOW_SECONDS = 120

FLOOD_MIN_COUNT = 15
FLOOD_WINDOW_SECONDS = 120


def _sliding_window_flag(items: list[tuple[int, int]], min_count: int, window: int) -> set[int]:
    """items: list of (ts, line_no), any order. Flags every line_no that is
    part of some run of >=min_count items all within `window` seconds of the
    run's start."""
    items = sorted(items)
    n = len(items)
    flagged: set[int] = set()
    for i in range(n):
        j = i
        while j + 1 < n and items[j + 1][0] - items[i][0] <= window:
            j += 1
        if j - i + 1 >= min_count:
            for k in range(i, j + 1):
                flagged.add(items[k][1])
    return flagged


def compute_burst_flags(rows: Iterable[tuple[int, Optional[str], int]]) -> set[int]:
    """rows: (line_no, origin, ts). Origin-less rows (the 423 pre-logging
    fragment lines) are grouped into one pseudo-origin, matching the measured
    baseline in the project plan (143,171 rows)."""
    by_origin: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for line_no, origin, ts in rows:
        key = origin if origin is not None else "\x00none\x00"
        by_origin[key].append((ts, line_no))
    flagged: set[int] = set()
    for items in by_origin.values():
        flagged |= _sliding_window_flag(items, BURST_MIN_COUNT, BURST_WINDOW_SECONDS)
    return flagged


def compute_flood_flags(
    rows: Iterable[tuple[int, Optional[str], str, int]]
) -> set[int]:
    """rows: (line_no, origin, name_lc, ts). Flags identical-name spam from
    one origin — the 'HACKED Gold' x900-in-22-minutes pattern — a stricter,
    distinct failure mode from a chat burst of varied messages."""
    groups: dict[tuple[Optional[str], str], list[tuple[int, int]]] = defaultdict(list)
    for line_no, origin, name_lc, ts in rows:
        groups[(origin, name_lc)].append((ts, line_no))
    flagged: set[int] = set()
    for items in groups.values():
        if len(items) < FLOOD_MIN_COUNT:
            continue
        flagged |= _sliding_window_flag(items, FLOOD_MIN_COUNT, FLOOD_WINDOW_SECONDS)
    return flagged


def compute_repost_flags(
    rows: Iterable[tuple[int, Optional[str], str]]
) -> set[int]:
    """rows: (line_no, origin, name_lc) IN FILE ORDER (== upload order, since
    the log is append-only). Flags a row if this exact (origin, name) pair
    was already seen earlier in the file."""
    seen: set[tuple[Optional[str], str]] = set()
    flagged: set[int] = set()
    for line_no, origin, name_lc in rows:
        key = (origin, name_lc)
        if key in seen:
            flagged.add(line_no)
        else:
            seen.add(key)
    return flagged


ORIGIN_CHAT_RATIO = 0.55
ORIGIN_FLOOD_RATIO = 0.12


def origin_class(uploads: int, distinct_names: int) -> str:
    if uploads == 0:
        return "builder"
    ratio = distinct_names / uploads
    if ratio >= ORIGIN_CHAT_RATIO:
        return "chat"
    if ratio <= ORIGIN_FLOOD_RATIO:
        return "flooder"
    return "builder"


# ---------------------------------------------------------------------------
# Quality score — a list of named contributions, not just a total, so the
# detail panel can show *why* a world scored what it did.
# ---------------------------------------------------------------------------

_CATEGORY_WEIGHTS = {
    cat: (3.0 if cat in ("realworld", "gameplay") else 1.5) for cat in terms.KEYWORDS
}
_CATEGORY_CAP = 9.0
_JUNK_PENALTY = 8.0

_KEYWORD_PATTERNS = {
    cat: [re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in words]
    for cat, words in terms.KEYWORDS.items()
}


def score_world(
    *,
    name: str,
    flags: int,
    series_depth: int,
    version_ordinal: Optional[float],
    author: Optional[str],
    featured_snapshots: int,
) -> tuple[float, list[tuple[str, float]]]:
    parts: list[tuple[str, float]] = []

    def add(label: str, value: float) -> None:
        if value:
            parts.append((label, round(value, 1)))

    # Series depth is the strongest quality proxy in the corpus: nobody
    # reaches v27 of a world they didn't care about. `series_depth` is the
    # count of *distinct version numbers* actually reached, not raw row
    # count — a generic name like "Airport" gets reposted 30+ times by
    # unrelated builders with no version markers at all, which is popularity
    # noise, not iterative depth, and must not be confused with it.
    # Deliberately no "old = good" bonus — the 326 pre-2015 rows score on
    # their own merits.
    add("series depth", min(series_depth, 30) * 1.0)
    if version_ordinal and version_ordinal >= 2:
        add("high version number", min((version_ordinal - 1) * 0.3, 6.0))

    lname = name.lower()
    kw_total = 0.0
    hit_cats: list[str] = []
    for cat, patterns in _KEYWORD_PATTERNS.items():
        hits = sum(1 for p in patterns if p.search(lname))
        if hits:
            kw_total += min(hits * _CATEGORY_WEIGHTS[cat], _CATEGORY_CAP)
            hit_cats.append(cat)
    if kw_total:
        add(f"key terms ({', '.join(hit_cats)})", kw_total)

    if author:
        add("author attribution", 5.0)

    tokens = name.split()
    name_quality = 0.0
    if len(tokens) >= 2:
        name_quality += 2.0
    if any(c.isupper() for c in name) and any(c.islower() for c in name):
        name_quality += 1.0
    add("multi-word / mixed-case name", name_quality)

    if featured_snapshots:
        add(
            f"featured in {featured_snapshots} official snapshot(s)",
            min(15.0 + (featured_snapshots - 1) * 8.0, 60.0),
        )

    junk_hits = [f for f in JUNK_FLAG_NAMES if flags & (1 << FLAG_BITS[f])]
    if junk_hits:
        add(f"junk flags ({', '.join(junk_hits)})", -_JUNK_PENALTY * len(junk_hits))

    total = max(0.0, min(100.0, sum(v for _, v in parts)))
    return round(total, 1), parts
