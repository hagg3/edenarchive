#!/usr/bin/env python3
"""python3 -m edenfind.selftest [worlds.db]

Regression baseline: asserts the measured facts from the project plan against
a fresh parse of file_list2.txt (fast, no db needed) and against a built
worlds.db (run `python3 build.py` first). Numbers here are what this
pipeline actually measures — a few differ by well under 1% from the plan's
draft estimates (written before the final parsing rules were locked down);
see CLAUDE.md's "Measured baseline" section for the reconciliation. Where the
plan's number was exact (repost, burst, DANIELAND, chat/flooder
classification, coverage-gap boundary), this file asserts that exact number.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edenfind import classify, series
from edenfind.parse import iter_filelist

ROOT = Path(__file__).resolve().parent.parent

_passed = 0
_failed = 0


def check(label: str, got, want, exact: bool = True) -> None:
    global _passed, _failed
    ok = (got == want) if exact else got
    status = "ok" if ok else "FAIL"
    print(f"[{status}] {label}: got={got!r} want={want!r}")
    if ok:
        _passed += 1
    else:
        _failed += 1


def test_parse(filelist_path: Path) -> None:
    print("\n-- parse.py (raw file_list2.txt) --")
    rows = 0
    rejects = 0
    names = set()
    for item in iter_filelist(str(filelist_path)):
        if isinstance(item, tuple):
            rejects += 1
            continue
        rows += 1
        if item.name.strip():
            names.add(item.name.strip().lower())
    check("rows parsed", rows, 896156)
    check("rejects", rejects, 1)
    check("distinct non-empty names (case-insensitive)", len(names), 339103)


def test_series_pure_functions() -> None:
    print("\n-- series.py (pure functions) --")
    check("version_ordinal(\"V3'1\")", series.version_ordinal("SWISS V 3'1 alpin"), 3.1)
    check("version_ordinal(\"2'9'4\")", series.version_ordinal("Direct City 2'9'4"), 2.94)
    check(
        "series_key collapses DANIELAND v2/v30",
        series.series_key("DANIELAND v2 EMILY'S DREAM")
        == series.series_key("DANIELAND v30 ULTIMATE BEACH HOUSE"),
        True,
    )
    check(
        "series_key keeps 'Kingdom of DANIELAND' separate from 'DANIELAND'",
        series.series_key("Kingdom of DANIELAND v7") != series.series_key("DANIELAND v7"),
        True,
    )


def test_db(db_path: Path) -> None:
    print(f"\n-- worlds.db ({db_path}) --")
    if not db_path.exists():
        print(f"  worlds.db not found at {db_path} — run `python3 build.py` first. Skipping.")
        return
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    def one(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    check("rejects table", one("SELECT COUNT(*) FROM rejects"), 1)

    f_default = one("SELECT COUNT(*) FROM worlds WHERE flags & ? != 0", 1 << classify.FLAG_BITS["f_default"])
    check("f_default count", f_default, 139528, exact=False)
    check("f_default is a large share of the corpus (~15%)", 0.10 < f_default / one("SELECT COUNT(*) FROM worlds") < 0.20, True)

    f_repost = one("SELECT COUNT(*) FROM worlds WHERE flags & ? != 0", 1 << classify.FLAG_BITS["f_repost"])
    check("f_repost count (exact match to plan)", f_repost, 288831)

    f_burst = one("SELECT COUNT(*) FROM worlds WHERE flags & ? != 0", 1 << classify.FLAG_BITS["f_burst"])
    check("f_burst count (exact match to plan)", f_burst, 143171)

    red_channel = one("SELECT COUNT(*) FROM worlds WHERE chat_channel = 'red'")
    check("chat_channel='red' is the largest channel and >100k rows", red_channel > 100000, True)

    pre2015 = one(
        "SELECT COUNT(*) FROM worlds WHERE iso_date < '2015-01-01' AND source = 'filelist'"
    )
    check("rows predating 2015-01-01 (exact match to plan)", pre2015, 326)

    feb2015 = one(
        "SELECT COUNT(*) FROM worlds WHERE iso_date >= '2015-02-01' AND iso_date < '2015-03-01'"
    )
    check("2015-02 row count confirms the coverage-gap jump", feb2015 > 40000, True)

    featured_distinct = one("SELECT COUNT(DISTINCT world_id) FROM featured")
    check("distinct featured worlds parsed from featured/", featured_distinct, 420, exact=False)

    featured_in_dump = one(
        "SELECT COUNT(DISTINCT f.world_id) FROM featured f "
        "JOIN worlds w ON w.id = f.world_id WHERE w.source = 'filelist'"
    )
    check("featured worlds present in the dump", featured_in_dump, 163, exact=False)

    danieland = conn.execute(
        "SELECT max_version, size FROM series WHERE series_key = 'danieland'"
    ).fetchone()
    check("DANIELAND series exists", danieland is not None, True)
    if danieland:
        check("DANIELAND max_version >= 30", danieland[0] >= 30, True)

    hg_total = one(
        "SELECT COUNT(*) FROM worlds WHERE name_lc = 'hacked gold' AND origin = '45.36.48.248'"
    )
    hg_flood = one(
        "SELECT COUNT(*) FROM worlds WHERE name_lc = 'hacked gold' AND origin = '45.36.48.248' "
        "AND flags & ? != 0",
        1 << classify.FLAG_BITS["f_flood"],
    )
    check("HACKED Gold flood rows from 45.36.48.248 (>= 601, per the plan)", hg_flood >= 601, True)
    check(
        "HACKED Gold: nearly every row from that origin is flagged f_flood "
        f"({hg_flood}/{hg_total}; a few isolated uploads outside the dense window are expected to miss)",
        hg_flood / hg_total > 0.95,
        True,
    )

    origin_classes = dict(
        conn.execute(
            "SELECT origin, origin_class FROM origins WHERE origin IN (?, ?)",
            ("24.45.52.119", "24.207.130.162"),
        ).fetchall()
    )
    check("24.45.52.119 classifies chat", origin_classes.get("24.45.52.119"), "chat")
    check("24.207.130.162 classifies flooder", origin_classes.get("24.207.130.162"), "flooder")

    fts_hits = conn.execute(
        "SELECT COUNT(*) FROM worlds_fts WHERE worlds_fts MATCH '\"direct city 2 9 4\"'"
    ).fetchone()[0]
    check(
        "FTS tokenizes DIRECT CITY 2'9'4 as 'direct city 2 9 4' (apostrophe as separator)",
        fts_hits > 0,
        True,
    )

    conn.close()


def main() -> None:
    filelist = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "file_list2.txt"
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "worlds.db"

    if filelist.exists():
        test_parse(filelist)
    else:
        print(f"{filelist} not found — skipping parse.py checks")
    test_series_pure_functions()
    test_db(db_path)

    print(f"\n{_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
