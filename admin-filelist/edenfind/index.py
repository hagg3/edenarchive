"""Builds worlds.db from file_list2.txt + featured/*.txt in one pass.

`worlds.id` is a surrogate autoincrement key, assigned in a deterministic
order (file_list2.txt in line order, then the 257 featured-only worlds
sorted by ts) so that it is stable across rebuilds — which is what lets the
`triage` table survive a rebuild by keying on it. `worlds.ts` is the actual
game world id (a unix timestamp; see the project plan) used to build preview
URLs and to correlate with featured/*.txt.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from . import classify, series as series_mod, terms
from .parse import iter_featured, iter_filelist

SCHEMA = """
CREATE TABLE worlds (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    iso_date TEXT NOT NULL,
    name TEXT NOT NULL,
    name_lc TEXT NOT NULL,
    origin TEXT,
    origin_kind TEXT NOT NULL,
    source TEXT NOT NULL,
    line_no INTEGER,
    series_id INTEGER,
    version_ordinal REAL,
    author TEXT,
    chat_channel TEXT,
    quality_score REAL NOT NULL,
    score_parts TEXT NOT NULL,
    flags INTEGER NOT NULL
);
CREATE INDEX idx_worlds_ts ON worlds(ts);
CREATE INDEX idx_worlds_name_lc ON worlds(name_lc);
CREATE INDEX idx_worlds_series ON worlds(series_id);
CREATE INDEX idx_worlds_origin ON worlds(origin);
CREATE INDEX idx_worlds_flags ON worlds(flags);
CREATE INDEX idx_worlds_quality ON worlds(quality_score);
CREATE INDEX idx_worlds_iso_date ON worlds(iso_date);

CREATE VIRTUAL TABLE worlds_fts USING fts5(
    name, content='worlds', content_rowid='id', tokenize='unicode61'
);

CREATE TABLE distinct_names (id INTEGER PRIMARY KEY, name_lc TEXT UNIQUE NOT NULL);
CREATE TABLE name_ngrams (gram TEXT NOT NULL, name_id INTEGER NOT NULL);
CREATE INDEX idx_name_ngrams_gram ON name_ngrams(gram);

CREATE TABLE origins (
    origin TEXT PRIMARY KEY,
    uploads INTEGER NOT NULL,
    distinct_names INTEGER NOT NULL,
    distinct_ratio REAL NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    median_gap REAL,
    origin_class TEXT NOT NULL
);
CREATE INDEX idx_origins_class ON origins(origin_class);

CREATE TABLE series (
    series_id INTEGER PRIMARY KEY,
    series_key TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    size INTEGER NOT NULL,
    max_version REAL,
    first_ts INTEGER NOT NULL,
    last_ts INTEGER NOT NULL,
    best_world_id INTEGER NOT NULL
);
CREATE INDEX idx_series_size ON series(size);

CREATE TABLE featured (
    world_id INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    rank INTEGER NOT NULL,
    name_at_time TEXT NOT NULL
);
CREATE INDEX idx_featured_world ON featured(world_id);

CREATE TABLE triage (
    world_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    note TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE rejects (line_no INTEGER, raw TEXT);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE live_saved (
    ts INTEGER NOT NULL,
    server TEXT NOT NULL,
    name TEXT NOT NULL,
    note TEXT,
    saved_at TEXT NOT NULL,
    PRIMARY KEY (ts, server)
);
"""


def _iso_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def _trigrams(s: str) -> set[str]:
    s = f"  {s} "
    return {s[i : i + 3] for i in range(len(s) - 2)}


def _snapshot_date_from_path(path: str) -> str:
    m = re.search(r"(\d{8})", os.path.basename(path))
    d = m.group(1)
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def _median_gap(tss: list[int]) -> Optional[float]:
    if len(tss) < 2:
        return None
    gaps = [b - a for a, b in zip(tss, tss[1:])]
    return statistics.median(gaps)


def build(filelist_path: str, featured_dir: str, db_path: str) -> None:
    t0 = time.time()

    # ---- 1. Parse file_list2.txt into memory -----------------------------
    print("Parsing", filelist_path, "...", file=sys.stderr)
    rows: list[dict] = []
    rejects: list[tuple[int, str]] = []
    for item in iter_filelist(filelist_path):
        if isinstance(item, tuple):
            rejects.append(item)
            continue
        rows.append(
            {
                "line_no": item.line_no,
                "ts": item.ts,
                "name": item.name,
                "name_lc": item.name.lower(),
                "origin": item.origin,
                "origin_kind": item.origin_kind,
            }
        )
    print(f"  {len(rows)} rows, {len(rejects)} rejects", file=sys.stderr)

    # ---- 2. Corpus-wide flags: repost, burst, flood -----------------------
    print("Computing repost/burst/flood flags ...", file=sys.stderr)
    repost_flagged = classify.compute_repost_flags(
        (r["line_no"], r["origin"], r["name_lc"]) for r in rows
    )
    burst_flagged = classify.compute_burst_flags(
        (r["line_no"], r["origin"], r["ts"]) for r in rows
    )
    flood_flagged = classify.compute_flood_flags(
        (r["line_no"], r["origin"], r["name_lc"], r["ts"]) for r in rows
    )

    # ---- 3. Featured snapshots ---------------------------------------------
    print("Parsing featured/ snapshots ...", file=sys.stderr)
    featured_by_ts: dict[int, list[tuple[str, int, str]]] = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(featured_dir, "*.txt"))):
        snap_date = _snapshot_date_from_path(path)
        for frow in iter_featured(path, snap_date):
            featured_by_ts[frow.ts].append((frow.snapshot_date, frow.rank, frow.name))

    dump_ts = {r["ts"] for r in rows}
    missing_featured_ts = sorted(set(featured_by_ts) - dump_ts)
    print(
        f"  {len(featured_by_ts)} distinct featured ts, "
        f"{len(featured_by_ts) - len(missing_featured_ts)} present in dump, "
        f"{len(missing_featured_ts)} missing (pre-2015 coverage gap)",
        file=sys.stderr,
    )

    # Synthesize first-class rows for featured worlds absent from the dump.
    next_line_no = max((r["line_no"] for r in rows), default=0) + 1
    for ts in missing_featured_ts:
        # Most recent snapshot's spelling of the name wins.
        snaps = sorted(featured_by_ts[ts])
        name = snaps[-1][2]
        rows.append(
            {
                "line_no": next_line_no,
                "ts": ts,
                "name": name,
                "name_lc": name.lower(),
                "origin": None,
                "origin_kind": "none",
                "source": "featured",
            }
        )
        next_line_no += 1

    for r in rows:
        r.setdefault("source", "filelist")

    # ---- 4. Series ----------------------------------------------------------
    print("Computing series ...", file=sys.stderr)
    for r in rows:
        r["series_key"] = series_mod.series_key(r["name"]) if r["name"].strip() else ""
        r["version_ordinal"] = series_mod.version_ordinal(r["name"])

    series_members: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["series_key"]:
            series_members[r["series_key"]].append(r)

    # Depth = distinct version numbers actually reached, not raw row count —
    # see classify.score_world for why raw count would reward a generic
    # reposted name like "Airport" as if it were a deliberate iterative build.
    series_depth: dict[str, int] = {}
    for key, members in series_members.items():
        versions = {m["version_ordinal"] for m in members if m["version_ordinal"] is not None}
        if versions:
            series_depth[key] = len(versions)
        else:
            series_depth[key] = max(len({m["name_lc"] for m in members}) - 1, 0)

    # ---- 5. Origins -----------------------------------------------------------
    print("Computing origin stats ...", file=sys.stderr)
    origin_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["origin"] is not None:
            origin_rows[r["origin"]].append(r)

    origins_out = []
    for origin, orows in origin_rows.items():
        tss = sorted(x["ts"] for x in orows)
        distinct_names = len({x["name_lc"] for x in orows})
        uploads = len(orows)
        ratio = distinct_names / uploads
        origins_out.append(
            (
                origin,
                uploads,
                distinct_names,
                round(ratio, 4),
                tss[0],
                tss[-1],
                _median_gap(tss),
                classify.origin_class(uploads, distinct_names),
            )
        )

    # ---- 6. Score every row ----------------------------------------------------
    print("Scoring ...", file=sys.stderr)
    for r in rows:
        name = r["name"]
        empty = name.strip() == ""
        chat_channel = classify.detect_chat_channel(name) if not empty else None
        featured_snapshots = len(featured_by_ts.get(r["ts"], []))
        flags = classify.flags_mask(
            f_empty=empty,
            f_default=(not empty) and classify.is_default_name(name),
            f_chat_channel=chat_channel is not None,
            f_chat_words=(not empty) and classify.detect_chat_words(name),
            f_chat_escape=(not empty) and classify.detect_chat_escape(name),
            f_repost=r["line_no"] in repost_flagged,
            f_burst=r["line_no"] in burst_flagged,
            f_flood=r["line_no"] in flood_flagged,
            f_gibberish=(not empty) and classify.detect_gibberish(name),
            f_short=(not empty) and classify.detect_short(name),
            f_featured=featured_snapshots > 0,
        )
        r["flags"] = flags
        r["chat_channel"] = chat_channel
        r["author"] = classify.extract_author(name) if not empty else None
        depth = series_depth.get(r["series_key"], 0)
        score, parts = classify.score_world(
            name=name,
            flags=flags,
            series_depth=depth,
            version_ordinal=r["version_ordinal"],
            author=r["author"],
            featured_snapshots=featured_snapshots,
        )
        r["quality_score"] = score
        r["score_parts"] = json.dumps(parts)

    # ---- 7. Series table rows (needs quality_score for best_world_id) --------
    series_out = []
    series_id_by_key: dict[str, int] = {}
    for i, (key, members) in enumerate(sorted(series_members.items()), start=1):
        series_id_by_key[key] = i
        best = max(members, key=lambda x: x["quality_score"])
        versions = [m["version_ordinal"] for m in members if m["version_ordinal"] is not None]
        tss = [m["ts"] for m in members]
        display_name = min(members, key=lambda m: m["ts"])["name"]
        series_out.append(
            (
                i,
                key,
                display_name,
                len(members),
                max(versions) if versions else None,
                min(tss),
                max(tss),
                None,  # best_world_id filled after ids are assigned
            )
        )
        for m in members:
            m["series_id"] = i
            m["_is_best_in_series"] = m is best
    for r in rows:
        r.setdefault("series_id", None)
        r.setdefault("_is_best_in_series", False)

    # ---- 8. Write to SQLite -----------------------------------------------
    print("Writing", db_path, "...", file=sys.stderr)
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    rows.sort(key=lambda r: (r["source"] != "filelist", r["line_no"]))

    world_id_by_series_best: dict[int, int] = {}
    fts_rows = []
    name_id_by_lc: dict[str, int] = {}
    distinct_name_rows = []
    ngram_rows = []
    with conn:
        for r in rows:
            cur = conn.execute(
                "INSERT INTO worlds (ts, iso_date, name, name_lc, origin, origin_kind, "
                "source, line_no, series_id, version_ordinal, author, chat_channel, "
                "quality_score, score_parts, flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r["ts"],
                    _iso_date(r["ts"]),
                    r["name"],
                    r["name_lc"],
                    r["origin"],
                    r["origin_kind"],
                    r["source"],
                    r["line_no"],
                    r["series_id"],
                    r["version_ordinal"],
                    r["author"],
                    r["chat_channel"],
                    r["quality_score"],
                    r["score_parts"],
                    r["flags"],
                ),
            )
            world_id = cur.lastrowid
            r["id"] = world_id
            fts_rows.append((world_id, r["name"]))
            if r["_is_best_in_series"] and r["series_id"] is not None:
                world_id_by_series_best[r["series_id"]] = world_id
            if r["name_lc"] and r["name_lc"] not in name_id_by_lc:
                name_id = len(name_id_by_lc) + 1
                name_id_by_lc[r["name_lc"]] = name_id
                distinct_name_rows.append((name_id, r["name_lc"]))
                for g in _trigrams(r["name_lc"]):
                    ngram_rows.append((g, name_id))

        conn.executemany(
            "INSERT INTO worlds_fts (rowid, name) VALUES (?, ?)", fts_rows
        )
        conn.executemany(
            "INSERT INTO distinct_names VALUES (?, ?)", distinct_name_rows
        )
        conn.executemany(
            "INSERT INTO name_ngrams (gram, name_id) VALUES (?, ?)", ngram_rows
        )
        conn.executemany(
            "INSERT INTO origins VALUES (?,?,?,?,?,?,?,?)", origins_out
        )
        series_final = [
            (sid, key, disp, size, maxv, first_ts, last_ts, world_id_by_series_best.get(sid))
            for (sid, key, disp, size, maxv, first_ts, last_ts, _) in series_out
        ]
        conn.executemany(
            "INSERT INTO series VALUES (?,?,?,?,?,?,?,?)", series_final
        )
        featured_final = []
        for r in rows:
            for snap_date, rank, name_at_time in featured_by_ts.get(r["ts"], []):
                featured_final.append((r["id"], snap_date, rank, name_at_time))
        conn.executemany(
            "INSERT INTO featured VALUES (?,?,?,?)", featured_final
        )
        conn.executemany(
            "INSERT INTO rejects VALUES (?,?)", rejects
        )
        conn.executemany(
            "INSERT INTO meta VALUES (?,?)",
            [
                ("built_at", datetime.now(timezone.utc).isoformat()),
                ("source_file", os.path.abspath(filelist_path)),
                ("row_count", str(len(rows))),
                ("reject_count", str(len(rejects))),
            ],
        )

    conn.execute("ANALYZE")
    conn.close()
    print(f"Done in {time.time() - t0:.1f}s", file=sys.stderr)


def restore_triage(old_db_path: str, new_db_path: str) -> int:
    """Copies triage rows from a previous build into the freshly built db,
    matched by world id (stable across rebuilds — see module docstring)."""
    if not os.path.exists(old_db_path):
        return 0
    old = sqlite3.connect(old_db_path)
    try:
        triage_rows = old.execute(
            "SELECT world_id, status, note, updated_at FROM triage"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    finally:
        old.close()
    if not triage_rows:
        return 0
    new = sqlite3.connect(new_db_path)
    with new:
        valid_ids = {
            row[0]
            for row in new.execute("SELECT id FROM worlds").fetchall()
        }
        restorable = [row for row in triage_rows if row[0] in valid_ids]
        new.executemany(
            "INSERT OR REPLACE INTO triage VALUES (?,?,?,?)", restorable
        )
    new.close()
    return len(restorable)


def restore_live_saved(old_db_path: str, new_db_path: str) -> int:
    """Copies live_saved rows (worlds manually saved from live server
    browsing) into the freshly built db. Unlike triage, these have no
    connection to `worlds.id` — they're keyed on (ts, server) and are the
    only record of worlds that don't exist in file_list2.txt/featured/*.txt
    at all, so nothing here needs validating against the new build."""
    if not os.path.exists(old_db_path):
        return 0
    old = sqlite3.connect(old_db_path)
    try:
        rows = old.execute(
            "SELECT ts, server, name, note, saved_at FROM live_saved"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    finally:
        old.close()
    if not rows:
        return 0
    new = sqlite3.connect(new_db_path)
    with new:
        new.executemany(
            "INSERT OR REPLACE INTO live_saved VALUES (?,?,?,?,?)", rows
        )
    new.close()
    return len(rows)
