"""Tag inventory, near-dupe grouping, and safe bulk retagging.

Ported from z_scripts/tag manage/analyze_tags.py (difflib near-dupe grouping)
and merge_tags.py (tag_map application) — but every write here goes through
world.save -> frontmatter.render, never yaml.dump, so files never drift from
the corpus's hand-written formatting convention. See frontmatter.py's
docstring for why that matters; merge_tags.py's save_file() is what this
replaces and must not be reused.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path

import yaml

from . import world as world_mod

NEAR_DUPE_CUTOFF = 0.85


def normalize(tag: str) -> str:
    return tag.lower().strip()


@dataclass
class TagStats:
    tag: str
    count: int
    slugs: list[str]


def tag_inventory(worlds: list[world_mod.World]) -> list[TagStats]:
    by_tag: dict[str, list[str]] = defaultdict(list)
    for w in worlds:
        for t in w.tags:
            by_tag[t].append(w.slug)
    return sorted(
        (TagStats(tag=t, count=len(slugs), slugs=slugs) for t, slugs in by_tag.items()),
        key=lambda s: (-s.count, s.tag),
    )


def near_dupe_groups(tags: list[str], cutoff: float = NEAR_DUPE_CUTOFF) -> list[tuple[str, ...]]:
    """Groups of tags that look like the same word, e.g. ("sport", "sports").
    Real tags in the corpus are already all lowercase; this groups by string
    similarity (difflib.SequenceMatcher via get_close_matches), same cutoff
    analyze_tags.py used (0.85)."""
    normalized = sorted(set(tags))
    groups: set[tuple[str, ...]] = set()
    for tag in normalized:
        matches = get_close_matches(tag, normalized, n=10, cutoff=cutoff)
        group = tuple(sorted({tag, *matches}))
        if len(group) > 1:
            groups.add(group)
    return sorted(groups)


def load_tag_map(path: Path) -> dict[str, str]:
    """tag_map.yaml: `bad_tag: canonical_tag`. Read-only load — this file is
    hand-maintained by the archivist, never written by the app."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return {normalize(str(k)): normalize(str(v)) for k, v in data.items()}


def rewrite_tags(tags: list[str], tag_map: dict[str, str]) -> list[str]:
    """Apply tag_map to one world's tag list, then dedupe while preserving
    first-seen order (same behavior as merge_tags.py's dict.fromkeys)."""
    mapped = [tag_map.get(normalize(t), t) for t in tags]
    return list(dict.fromkeys(mapped))


@dataclass
class RetagPreview:
    slug: str
    before: list[str]
    after: list[str]


def preview_bulk_retag(worlds: list[world_mod.World], tag_map: dict[str, str]) -> list[RetagPreview]:
    """The dry-run: which worlds would change and how, without writing anything."""
    out = []
    for w in worlds:
        before = w.tags
        after = rewrite_tags(before, tag_map)
        if after != before:
            out.append(RetagPreview(slug=w.slug, before=before, after=after))
    return out


def apply_bulk_retag(worlds: list[world_mod.World], tag_map: dict[str, str]) -> list[str]:
    """Writes each changed world's tags through world.save (format-preserving).
    Returns the slugs that were actually rewritten on disk."""
    changed = []
    for w in worlds:
        after = rewrite_tags(w.tags, tag_map)
        if after != w.tags and world_mod.save(w, {"tags": after}):
            changed.append(w.slug)
    return changed
