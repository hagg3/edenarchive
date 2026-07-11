"""Duplicate & version-chain detection.

Two-tier hashing (core/hashing.py) plus name-similarity scoring, per
ADMIN_APP_PLAN.md's "Duplicate & version detection" section. Scores against
the SQLite index's cached fields (norm_name, base_name, zip_sha256,
payload_sha256) — payload hashes are populated separately by a background
job (core/hashing.hash_payload), not computed here. Pure stdlib difflib, no
new dependency — see the plan for why (n=768 doesn't justify rapidfuzz).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import yaml

NEAR_NAME_CUTOFF = 0.87
NEAR_NAME_JACCARD_CUTOFF = 0.8
SAME_AUTHOR_CUTOFF = 0.70
SAME_AUTHOR_WINDOW_DAYS = 90


@dataclass
class WorldForDupes:
    slug: str
    worldname: str
    author: str
    publishdate: str
    norm_name: str
    base_name: str
    version_token: str
    zip_sha256: str | None
    payload_sha256: str | None


@dataclass
class DupePair:
    a_slug: str
    b_slug: str
    reason: str
    score: float
    detail: str


def _tokens(norm_name: str) -> set[str]:
    return set(norm_name.split())


def _trigrams(s: str) -> set[str]:
    return {s[i : i + 3] for i in range(len(s) - 2)} if len(s) >= 3 else {s}


def _prefilter_candidate(a: WorldForDupes, b: WorldForDupes) -> bool:
    """Cheap check before the SequenceMatcher call: skip pairs that can't
    plausibly be near-name matches. Length ratio + shared token/3-gram, per
    the plan's sub-second budget at n=768 (294k raw pairs)."""
    la, lb = len(a.norm_name), len(b.norm_name)
    if la == 0 or lb == 0:
        return False
    if min(la, lb) / max(la, lb) < 0.5:
        return False
    if _tokens(a.norm_name) & _tokens(b.norm_name):
        return True
    return bool(_trigrams(a.norm_name) & _trigrams(b.norm_name))


def _parse_date(s: str | None) -> datetime | None:
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d")
    except ValueError:
        return None


def score_pairs(worlds: list[WorldForDupes]) -> list[DupePair]:
    """All candidate dupe/version pairs across `worlds`, scored per the table
    in ADMIN_APP_PLAN.md's "Candidate scoring" section."""
    pairs: list[DupePair] = []
    seen: set[tuple[str, str]] = set()

    def emit(wa: WorldForDupes, wb: WorldForDupes, reason: str, score: float, detail: str) -> bool:
        a, b = sorted((wa.slug, wb.slug))
        if (a, b) in seen:
            return False
        pairs.append(DupePair(a, b, reason, score, detail))
        seen.add((a, b))
        return True

    # Tier 1/2 hashes: group by hash, emit all pairs within each group.
    # Payload identity supersedes zip identity once known, so a pair already
    # covered by identical_payload never also gets identical_zip.
    by_payload: dict[str, list[WorldForDupes]] = {}
    by_zip: dict[str, list[WorldForDupes]] = {}
    for w in worlds:
        if w.payload_sha256:
            by_payload.setdefault(w.payload_sha256, []).append(w)
        elif w.zip_sha256:
            by_zip.setdefault(w.zip_sha256, []).append(w)

    for group in by_payload.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                emit(group[i], group[j], "identical_payload", 1.00, "same payload sha256")

    for group in by_zip.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                emit(
                    group[i], group[j], "identical_zip", 0.98,
                    "same zip sha256, payload not yet hashed",
                )

    # Version chains: same base_name, at least one side has a version token.
    by_base: dict[str, list[WorldForDupes]] = {}
    for w in worlds:
        if w.base_name:
            by_base.setdefault(w.base_name, []).append(w)
    for base, group in by_base.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                wa, wb = group[i], group[j]
                if wa.version_token or wb.version_token:
                    emit(wa, wb, "version_chain", 0.90, f"shared base name {base!r}")

    # Near-name + same-author-similar: pairwise with a cheap prefilter.
    n = len(worlds)
    for i in range(n):
        wa = worlds[i]
        for j in range(i + 1, n):
            wb = worlds[j]
            if (tuple(sorted((wa.slug, wb.slug)))) in seen:
                continue
            if not _prefilter_candidate(wa, wb):
                continue

            ratio = SequenceMatcher(None, wa.norm_name, wb.norm_name).ratio()
            ta, tb = _tokens(wa.norm_name), _tokens(wb.norm_name)
            jaccard = len(ta & tb) / len(ta | tb) if (ta or tb) else 0.0

            if ratio >= NEAR_NAME_CUTOFF or jaccard >= NEAR_NAME_JACCARD_CUTOFF:
                emit(wa, wb, "near_name", ratio, f"name similarity {ratio:.2f}")
                continue

            if wa.author and wb.author and wa.author == wb.author and ratio >= SAME_AUTHOR_CUTOFF:
                da, db = _parse_date(wa.publishdate), _parse_date(wb.publishdate)
                if da and db and abs((da - db).days) <= SAME_AUTHOR_WINDOW_DAYS:
                    score = 0.70 + 0.3 * ratio
                    emit(
                        wa, wb, "same_author_similar", score,
                        f"same author, {ratio:.2f} name similarity, "
                        f"{abs((da - db).days)}d apart",
                    )

    return pairs


# --- dismissal persistence ----------------------------------------------------
#
# The SQLite index is disposable (rebuilds from the markdown corpus on
# demand), except for dismissed-dupe decisions — those also get appended
# here, to a file that IS committed, so a DB wipe never loses a decision an
# archivist already made.

def load_dismissals(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else []


def append_dismissal(path: Path, a_slug: str, b_slug: str, reason: str, note: str = "") -> None:
    entries = load_dismissals(path)
    a, b = sorted((a_slug, b_slug))
    entries.append(
        {
            "a_slug": a, "b_slug": b, "reason": reason, "note": note,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    text = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
