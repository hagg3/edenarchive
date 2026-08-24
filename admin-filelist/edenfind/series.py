"""Series recovery: group a version-numbered world across its whole run and
sort it in true build order.

Validated against DANIELAND (v1-v30, plus the "MIDEVIL DANIELAND" and
"Kingdom of DANIELAND" sub-lines, which must stay *separate* series because
they're different builds under a shared name fragment), SNC Arena (v10-v19),
Party Park, Olympic Village and Rebelbirdys ("Part 1-10") — all collapse
correctly with the rules below.

Apostrophe-as-decimal (see the project plan): the game keyboard has no ".",
so builders write version numbers with apostrophes as separators —
"V3'1" means 3.1, and "2'9'4" means 2.94 (the segments after the first are
concatenated, not summed, into the fractional part).
"""
from __future__ import annotations

import re
from typing import Optional

from . import terms

_SEASON_EP_RE = r"\bs\d+\s*ep\d+\b"
_VERSION_WORD_RE = (
    r"\b(?:v|ver|version|rev|revision|build|upd|update|part|pt|episode|ep|season)"
    r"\.?\s*\d+(?:'\d+)*[a-z]?\b"
)
_APOS_DECIMAL_RE = r"\b\d+(?:'\d+)+\b"
_NUM_RANGE_RE = r"\b\d+\s*-\s*\d+\b"
_TRAILING_NUM_RE = r"\b\d+\b\s*$"

# A version marker truncates the name, rather than being cut out in place:
# per-version subtitles ("DANIELAND v30 ULTIMATE BEACH HOUSE", "DANIELAND
# v26 THE BIG HOUSE") are changelog text for that release, not part of the
# series' identity, so keeping them would fragment v1..v30 into 30 different
# series instead of one. Alternation order matters: the more specific
# patterns (explicit version words, apostrophe-decimal chains, numeric
# ranges) are tried before the last-resort trailing bare number, so a
# mid-name number that happens to be at the end of the string doesn't win
# over a real version word earlier in the name.
_TRUNCATE_RE = re.compile(
    "|".join(
        f"(?:{p})"
        for p in (_SEASON_EP_RE, _VERSION_WORD_RE, _APOS_DECIMAL_RE, _NUM_RANGE_RE, _TRAILING_NUM_RE)
    ),
    re.IGNORECASE,
)

_ITERATION_STRIP_WORDS = sorted(
    set(terms.KEYWORDS["iteration"]) | {"final", "fixed", "fix", "new", "old"},
    key=len,
    reverse=True,
)
_ITERATION_STRIP_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _ITERATION_STRIP_WORDS) + r")\b",
    re.IGNORECASE,
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_WS_RE = re.compile(r"\s+")


def series_key(name: str) -> str:
    s = name.lower()
    m = _TRUNCATE_RE.search(s)
    if m:
        s = s[: m.start()]
    s = _ITERATION_STRIP_RE.sub(" ", s)
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


_VERSION_NUM_RE = re.compile(
    r"\b(?:v|ver|version)\.?\s*(\d+(?:'\d+)*)\b", re.IGNORECASE
)
_BARE_APOS_DECIMAL_RE = re.compile(r"\b(\d+(?:'\d+)+)\b")
_TRAILING_INT_RE = re.compile(r"\b(\d+)\b")


def _ordinal_from_segments(chain: str) -> float:
    segs = chain.split("'")
    integer_part = segs[0]
    frac = "".join(segs[1:])
    return float(f"{integer_part}.{frac}") if frac else float(integer_part)


# The deepest genuine series observed in this corpus is DANIELAND at v31
# (see the project plan / CLAUDE.md). A "version" number far beyond that is
# essentially never real — it's a date (V25032021), a phone-mash, or a
# random id — and letting it through inflates series_key collisions between
# *unrelated* builders who happened to both name their world "Airport <n>"
# into looking like one deliberate, deeply-iterated build.
_MAX_PLAUSIBLE_VERSION = 200.0


def version_ordinal(name: str) -> Optional[float]:
    m = _VERSION_NUM_RE.search(name)
    if m:
        val = _ordinal_from_segments(m.group(1))
        return val if val <= _MAX_PLAUSIBLE_VERSION else None
    m = _BARE_APOS_DECIMAL_RE.search(name)
    if m:
        val = _ordinal_from_segments(m.group(1))
        return val if val <= _MAX_PLAUSIBLE_VERSION else None
    matches = _TRAILING_INT_RE.findall(name)
    if matches:
        val = float(matches[-1])
        return val if val <= _MAX_PLAUSIBLE_VERSION else None
    return None
