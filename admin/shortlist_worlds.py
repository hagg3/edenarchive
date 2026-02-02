#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


# ----------------------------
# Configuration (easy to tweak)
# ----------------------------

KEYWORDS = {
    "iteration": [
        "alpha", "beta", "prototype", "test", "rev", "revision", "build",
        "update", "pass", "phase", "draft", "concept", "wip", "v1", "v2", "v3", "v4", "v5",
    ],
    "architecture": [
        "station", "base", "outpost", "hub", "terminal", "dock", "port",
        "facility", "plant", "complex", "control", "sector", "zone", "module",
    ],
    "worldbuilding": [
        "city", "district", "capital", "ruins", "colony", "settlement",
        "stronghold", "citadel", "fort", "realm", "domain", "archive",
    ],
    "realworld": [
        "museum", "library", "airport", "hospital", "school", "factory",
        "laboratory", "research", "observatory", "bunker", "vault",
    ],
    "gameplay": [
        "adventure", "quest", "puzzle", "maze", "parkour", "challenge",
        "arena", "ctf", "rpg", "survival",
    ],
    "older": [
        "classic", "old", "legacy", "original", "remake", "redux", "definitive", "final",
    ],
    "other": [
        "unfinished", "abandoned", "experiment", "testbed", "sandbox", "replica", "project",
    ],
}

STRONG_KEYWORDS = set(
    KEYWORDS["realworld"]
    + KEYWORDS["gameplay"]
    + ["facility", "complex", "station", "base", "citadel", "stronghold", "replica"]
)

# Require at least this many category hits OR at least one strong keyword
MIN_CATEGORY_HITS = 2
REQUIRE_STRONG_IF_BELOW_MIN = True

# Cap how many variations per "series" name before final filtering
MAX_PER_SERIES = 3


# ----------------------------
# Helpers
# ----------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WORLD_ID_RE = re.compile(r"(\d{6,})\.eden$")
ROMAN_RE = re.compile(r"\b[IVX]{2,}\b", re.IGNORECASE)
VERSION_RE = re.compile(r"\b(v|ver|version)\s*\d+\b", re.IGNORECASE)
BRACKET_RE = re.compile(r"\[(wip|beta|alpha|v\d+)\]", re.IGNORECASE)
YEAR_RE = re.compile(r"\b20(0\d|1\d|2[0-6])\b")
HYPHEN_RE = re.compile(r"\b\w+-\w+\b")


def compile_keyword_patterns() -> Dict[str, List[re.Pattern]]:
    return {
        group: [re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in words]
        for group, words in KEYWORDS.items()
    }


def load_archived_ids(world_dir: Path) -> set:
    ids = set()
    for md in world_dir.glob("*.md"):
        text = md.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^filename:\s*([0-9]{6,})\.eden\s*$", text, re.MULTILINE)
        if m:
            ids.add(m.group(1))
    return ids


def parse_file_list(path: Path):
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip("\n")
            if not line.strip():
                continue
            parts = line.split(" ", 1)
            filename = parts[0]
            name = parts[1].strip() if len(parts) > 1 else ""
            if not filename.endswith(".eden"):
                continue
            yield filename, name


def series_key(name: str) -> str:
    # Remove versions, update words, years, and roman numerals for grouping
    cleaned = VERSION_RE.sub("", name)
    cleaned = re.sub(r"\bv\d+\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(beta|alpha|update|pass|phase|draft|rev|revision)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = YEAR_RE.sub("", cleaned)
    cleaned = ROMAN_RE.sub("", cleaned)
    cleaned = re.sub(r"[^a-z0-9 ]", " ", cleaned.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or name.lower().strip()


def score_name(name: str, word_re: Dict[str, List[re.Pattern]]) -> Tuple[int, List[str], int]:
    signals = []
    score = 0
    for group, regexes in word_re.items():
        if any(r.search(name) for r in regexes):
            signals.append(group)
            score += 1

    if ROMAN_RE.search(name):
        signals.append("roman")
        score += 1
    if VERSION_RE.search(name) or BRACKET_RE.search(name) or re.search(r"\bv\d+\b", name, re.IGNORECASE):
        signals.append("version")
        score += 1
    if YEAR_RE.search(name):
        signals.append("year")
        score += 1
    if HYPHEN_RE.search(name):
        signals.append("hyphen")
        score += 1

    strong_hits = sum(
        1 for w in STRONG_KEYWORDS if re.search(r"\b" + re.escape(w) + r"\b", name, re.IGNORECASE)
    )
    return score, signals, strong_hits


def pick_latest_per_series(candidates: List[dict]) -> List[dict]:
    latest = {}
    for c in candidates:
        key = c["series_key"]
        # Higher world ID == later timestamp
        if key not in latest or int(c["id"]) > int(latest[key]["id"]):
            latest[key] = c
    return list(latest.values())


def main():
    parser = argparse.ArgumentParser(description="Shortlist Eden worlds from server file list")
    parser.add_argument("--list", required=True, help="Path to file list (e.g. file_list2 260202.txt)")
    parser.add_argument("--worlds", default="_worlds", help="Path to _worlds directory")
    parser.add_argument("--out", default="admin/reports/shortlist.txt", help="Output text file")
    parser.add_argument("--json", default="admin/reports/shortlist.json", help="Output JSON file")
    parser.add_argument("--max", type=int, default=200, help="Max results to write (after filtering)")
    args = parser.parse_args()

    list_path = Path(args.list).expanduser().resolve()
    worlds_dir = Path(args.worlds).expanduser().resolve()
    out_txt = Path(args.out).expanduser().resolve()
    out_json = Path(args.json).expanduser().resolve()

    if not list_path.exists():
        print(f"ERROR: list file not found: {list_path}")
        return 1
    if not worlds_dir.exists():
        print(f"ERROR: worlds dir not found: {worlds_dir}")
        return 1

    archived_ids = load_archived_ids(worlds_dir)
    word_re = compile_keyword_patterns()

    candidates = []
    seen_names = set()

    for filename, name in parse_file_list(list_path):
        world_id = filename[:-5]
        if world_id in archived_ids:
            continue
        if not name or len(name) < 3:
            continue

        norm = re.sub(r"\s+", " ", name.strip()).lower()
        if norm in seen_names:
            continue

        score, signals, strong_hits = score_name(name, word_re)

        if score < MIN_CATEGORY_HITS and REQUIRE_STRONG_IF_BELOW_MIN and strong_hits == 0:
            continue

        seen_names.add(norm)
        candidates.append(
            {
                "id": world_id,
                "name": name,
                "score": score,
                "signals": signals,
                "strong_hits": strong_hits,
                "series_key": series_key(name),
            }
        )

    # Reduce series to latest ID and optionally cap per-series beforehand
    if MAX_PER_SERIES > 0:
        per_series = {}
        for c in sorted(candidates, key=lambda x: (x["series_key"], int(x["id"])), reverse=True):
            key = c["series_key"]
            per_series.setdefault(key, [])
            if len(per_series[key]) < MAX_PER_SERIES:
                per_series[key].append(c)
        capped = [c for group in per_series.values() for c in group]
    else:
        capped = candidates

    latest = pick_latest_per_series(capped)

    # Sort by strong hits then score, then newest
    latest.sort(key=lambda r: (r["strong_hits"], r["score"], int(r["id"])), reverse=True)

    latest = latest[: args.max]

    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    with out_txt.open("w", encoding="utf-8") as f:
        for r in latest:
            sig = ",".join(r["signals"]) if r["signals"] else "-"
            f.write(f"{r['id']}\\t{r['name']}\\t(sig={sig})\\n")

    with out_json.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "criteria": {
                    "min_category_hits": MIN_CATEGORY_HITS,
                    "require_strong_if_below_min": REQUIRE_STRONG_IF_BELOW_MIN,
                    "max_per_series": MAX_PER_SERIES,
                    "strong_keywords": sorted(STRONG_KEYWORDS),
                    "keywords": KEYWORDS,
                },
                "results": latest,
            },
            f,
            indent=2,
        )

    print(f"Wrote shortlist: {out_txt}")
    print(f"Wrote shortlist (json): {out_json}")
    print(f"Total candidates: {len(latest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
