"""SQLite cache over the markdown corpus.

Disposable by design: markdown is the source of truth and this can be deleted and
rebuilt at any time. The one thing that must NOT live only here is dupe
dismissals, which also append to the committed admin/dupe_dismissals.yaml.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import paths
from . import world as world_mod

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS worlds (
  slug TEXT PRIMARY KEY, md_path TEXT NOT NULL, world_id TEXT,
  layout TEXT, filename TEXT, worldname TEXT, publishdate TEXT,
  archivedate TEXT, filesize TEXT, author TEXT,
  fm_key_order TEXT,
  md_mtime_ns INTEGER, md_size INTEGER, md_sha256 TEXT,
  asset_dir TEXT,
  has_zip INTEGER, zip_path TEXT, zip_bytes INTEGER, zip_sha256 TEXT, zip_mtime_ns INTEGER,
  has_preview INTEGER, preview_bytes INTEGER,
  has_map INTEGER, map_bytes INTEGER, map_mtime_ns INTEGER,
  payload_sha256 TEXT, payload_bytes INTEGER,
  payload_hashed_at TEXT, payload_error TEXT,
  map_status TEXT, map_error TEXT,
  norm_name TEXT, base_name TEXT, version_token TEXT,
  issues TEXT, indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_worlds_base    ON worlds(base_name);
CREATE INDEX IF NOT EXISTS idx_worlds_payload ON worlds(payload_sha256);
CREATE INDEX IF NOT EXISTS idx_worlds_zipsha  ON worlds(zip_sha256);

CREATE TABLE IF NOT EXISTS world_tags (
  slug TEXT REFERENCES worlds(slug) ON DELETE CASCADE,
  tag TEXT NOT NULL, pos INTEGER NOT NULL,
  PRIMARY KEY (slug, tag)
);
CREATE INDEX IF NOT EXISTS idx_world_tags_tag ON world_tags(tag);

-- Deliberately NOT contentless: a contentless fts5 table cannot service the
-- per-slug DELETE the incremental scan does on every rewrite.
CREATE VIRTUAL TABLE IF NOT EXISTS worlds_fts USING fts5(
  slug UNINDEXED, worldname, author, tags, body
);

CREATE TABLE IF NOT EXISTS dupe_pairs (
  a_slug TEXT, b_slug TEXT, reason TEXT,
  score REAL, detail TEXT,
  status TEXT DEFAULT 'new', status_note TEXT, status_at TEXT,
  PRIMARY KEY (a_slug, b_slug, reason)
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT, target TEXT, params TEXT,
  status TEXT, result TEXT, error_class TEXT,
  queued_at TEXT, started_at TEXT, ended_at TEXT
);

CREATE TABLE IF NOT EXISTS job_logs (
  job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
  seq INTEGER, ts TEXT, stream TEXT, line TEXT,
  PRIMARY KEY (job_id, seq)
);
"""

ISSUE_KINDS = [
    "invalid_front_matter",
    "missing_filename",
    "invalid_filename_format",
    "missing_asset_dir",
    "missing_zip",
    "missing_preview",
    "missing_map",
    "missing_tags",
    "invalid_tags",
    "invalid_publishdate",
    "invalid_archivedate",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def now() -> str:
    return _now()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    paths.ensure_runtime_dirs()
    conn = sqlite3.connect(db_path or paths.INDEX_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _stat(path: Path | None) -> tuple[bool, int, int]:
    if not path or not path.exists():
        return False, 0, 0
    st = path.stat()
    return True, st.st_size, st.st_mtime_ns


def scan(conn: sqlite3.Connection, *, force: bool = False) -> dict[str, int]:
    """Incremental rescan of _worlds. Unchanged files (same mtime_ns + size) are
    skipped; zip hashes are recomputed only when the zip's mtime changed.

    Payload hashing is deliberately NOT done here — that is a background job.
    """
    stats = {"scanned": 0, "updated": 0, "skipped": 0, "removed": 0}

    existing = {
        r["slug"]: r
        for r in conn.execute(
            "SELECT slug, md_mtime_ns, md_size, zip_mtime_ns, zip_sha256 FROM worlds"
        )
    }
    seen: set[str] = set()

    for md_path in sorted(paths.WORLDS_DIR.glob("*.md")):
        stats["scanned"] += 1
        slug = md_path.stem
        seen.add(slug)
        st = md_path.stat()
        prev = existing.get(slug)

        if (
            not force
            and prev
            and prev["md_mtime_ns"] == st.st_mtime_ns
            and prev["md_size"] == st.st_size
        ):
            stats["skipped"] += 1
            continue

        w = world_mod.load(md_path)
        has_zip, zip_bytes, zip_mtime = _stat(w.zip_path)
        has_prev, prev_bytes, _ = _stat(w.preview_path)
        has_map, map_bytes, map_mtime = _stat(w.map_path)

        zip_sha = None
        if has_zip:
            if prev and prev["zip_mtime_ns"] == zip_mtime and prev["zip_sha256"]:
                zip_sha = prev["zip_sha256"]
            else:
                zip_sha = _sha256_file(w.zip_path)

        norm = world_mod.normalize_name(w.worldname or slug)
        base, tokens = world_mod.strip_version(norm)

        conn.execute(
            """
            INSERT INTO worlds (
              slug, md_path, world_id, layout, filename, worldname, publishdate,
              archivedate, filesize, author, fm_key_order,
              md_mtime_ns, md_size, md_sha256, asset_dir,
              has_zip, zip_path, zip_bytes, zip_sha256, zip_mtime_ns,
              has_preview, preview_bytes, has_map, map_bytes, map_mtime_ns,
              map_status, norm_name, base_name, version_token, issues, indexed_at
            ) VALUES (
              :slug,:md_path,:world_id,:layout,:filename,:worldname,:publishdate,
              :archivedate,:filesize,:author,:fm_key_order,
              :md_mtime_ns,:md_size,:md_sha256,:asset_dir,
              :has_zip,:zip_path,:zip_bytes,:zip_sha256,:zip_mtime_ns,
              :has_preview,:preview_bytes,:has_map,:map_bytes,:map_mtime_ns,
              :map_status,:norm_name,:base_name,:version_token,:issues,:indexed_at
            )
            ON CONFLICT(slug) DO UPDATE SET
              md_path=excluded.md_path, world_id=excluded.world_id,
              layout=excluded.layout, filename=excluded.filename,
              worldname=excluded.worldname, publishdate=excluded.publishdate,
              archivedate=excluded.archivedate, filesize=excluded.filesize,
              author=excluded.author, fm_key_order=excluded.fm_key_order,
              md_mtime_ns=excluded.md_mtime_ns, md_size=excluded.md_size,
              md_sha256=excluded.md_sha256, asset_dir=excluded.asset_dir,
              has_zip=excluded.has_zip, zip_path=excluded.zip_path,
              zip_bytes=excluded.zip_bytes, zip_sha256=excluded.zip_sha256,
              zip_mtime_ns=excluded.zip_mtime_ns,
              has_preview=excluded.has_preview, preview_bytes=excluded.preview_bytes,
              has_map=excluded.has_map, map_bytes=excluded.map_bytes,
              map_mtime_ns=excluded.map_mtime_ns,
              map_status=excluded.map_status, norm_name=excluded.norm_name,
              base_name=excluded.base_name, version_token=excluded.version_token,
              issues=excluded.issues, indexed_at=excluded.indexed_at
            """,
            {
                "slug": slug,
                "md_path": str(md_path.relative_to(paths.REPO_ROOT)),
                "world_id": w.world_id,
                "layout": str(w.data.get("layout") or ""),
                "filename": str(w.data.get("filename") or ""),
                "worldname": w.worldname,
                "publishdate": w.publishdate,
                "archivedate": w.archivedate,
                "filesize": w.filesize,
                "author": w.author,
                "fm_key_order": json.dumps(w.doc.key_order),
                "md_mtime_ns": st.st_mtime_ns,
                "md_size": st.st_size,
                "md_sha256": _sha256_file(md_path),
                "asset_dir": str(w.asset_dir) if w.asset_dir else None,
                "has_zip": int(has_zip),
                "zip_path": str(w.zip_path) if w.zip_path else None,
                "zip_bytes": zip_bytes,
                "zip_sha256": zip_sha,
                "zip_mtime_ns": zip_mtime,
                "has_preview": int(has_prev),
                "preview_bytes": prev_bytes,
                "has_map": int(has_map),
                "map_bytes": map_bytes,
                "map_mtime_ns": map_mtime,
                "map_status": "ok" if has_map else "missing",
                "norm_name": norm,
                "base_name": base,
                "version_token": " ".join(tokens),
                "issues": json.dumps(w.issues),
                "indexed_at": _now(),
            },
        )

        conn.execute("DELETE FROM world_tags WHERE slug=?", (slug,))
        conn.executemany(
            "INSERT OR IGNORE INTO world_tags (slug, tag, pos) VALUES (?,?,?)",
            [(slug, t, i) for i, t in enumerate(w.tags)],
        )

        conn.execute("DELETE FROM worlds_fts WHERE slug=?", (slug,))
        conn.execute(
            "INSERT INTO worlds_fts (slug, worldname, author, tags, body) VALUES (?,?,?,?,?)",
            (slug, w.worldname, w.author, " ".join(w.tags), w.body),
        )
        stats["updated"] += 1

    for slug in set(existing) - seen:
        conn.execute("DELETE FROM worlds WHERE slug=?", (slug,))
        conn.execute("DELETE FROM world_tags WHERE slug=?", (slug,))
        conn.execute("DELETE FROM worlds_fts WHERE slug=?", (slug,))
        stats["removed"] += 1

    conn.execute(
        "INSERT INTO meta (key,value) VALUES ('last_scan',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_now(),),
    )
    conn.commit()
    return stats


# --- queries --------------------------------------------------------------

def counts(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(has_zip) AS zips,
               SUM(has_preview) AS previews,
               SUM(has_map) AS maps,
               SUM(zip_bytes) AS zip_bytes
        FROM worlds
        """
    ).fetchone()
    out = dict(row)
    out["missing_zip"] = (out["total"] or 0) - (out["zips"] or 0)
    out["missing_preview"] = (out["total"] or 0) - (out["previews"] or 0)
    out["missing_map"] = (out["total"] or 0) - (out["maps"] or 0)
    out["tags"] = conn.execute(
        "SELECT COUNT(DISTINCT tag) FROM world_tags"
    ).fetchone()[0]
    out["untagged"] = conn.execute(
        "SELECT COUNT(*) FROM worlds w WHERE NOT EXISTS "
        "(SELECT 1 FROM world_tags t WHERE t.slug=w.slug)"
    ).fetchone()[0]
    out["authors"] = conn.execute(
        "SELECT COUNT(DISTINCT author) FROM worlds WHERE author<>''"
    ).fetchone()[0]
    last = conn.execute("SELECT value FROM meta WHERE key='last_scan'").fetchone()
    out["last_scan"] = last[0] if last else None
    return out


def issue_tallies(conn: sqlite3.Connection) -> dict[str, int]:
    tallies = {k: 0 for k in ISSUE_KINDS}
    for (raw,) in conn.execute("SELECT issues FROM worlds WHERE issues <> '[]'"):
        for issue in json.loads(raw):
            if issue in tallies:
                tallies[issue] += 1
    return {k: v for k, v in tallies.items() if v}


def all_tags(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT tag, COUNT(*) AS n FROM world_tags GROUP BY tag ORDER BY n DESC, tag"
        )
    )


def all_authors(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT author FROM worlds WHERE author<>'' ORDER BY author COLLATE NOCASE"
        )
    ]


SORTS = {
    "name": "worldname COLLATE NOCASE ASC",
    "name_desc": "worldname COLLATE NOCASE DESC",
    "date": "publishdate DESC",
    "date_asc": "publishdate ASC",
    "author": "author COLLATE NOCASE ASC, worldname COLLATE NOCASE ASC",
    "size": "zip_bytes DESC",
}


def search(
    conn: sqlite3.Connection,
    *,
    q: str = "",
    tag: str = "",
    author: str = "",
    asset: str = "",
    issue: str = "",
    sort: str = "name",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[sqlite3.Row], int]:
    where: list[str] = []
    params: list[Any] = []

    if q.strip():
        where.append(
            "w.slug IN (SELECT slug FROM worlds_fts WHERE worlds_fts MATCH ?)"
        )
        params.append(_fts_query(q))
    if tag:
        where.append("EXISTS (SELECT 1 FROM world_tags t WHERE t.slug=w.slug AND t.tag=?)")
        params.append(tag)
    if author:
        where.append("w.author = ?")
        params.append(author)
    if asset == "missing_map":
        where.append("w.has_map = 0")
    elif asset == "missing_preview":
        where.append("w.has_preview = 0")
    elif asset == "missing_zip":
        where.append("w.has_zip = 0")
    elif asset == "complete":
        where.append("w.has_map=1 AND w.has_preview=1 AND w.has_zip=1")
    if issue == "any":
        where.append("w.issues <> '[]'")
    elif issue:
        where.append("w.issues LIKE ?")
        params.append(f'%"{issue}"%')

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    order = SORTS.get(sort, SORTS["name"])

    total = conn.execute(
        f"SELECT COUNT(*) FROM worlds w {clause}", params
    ).fetchone()[0]
    rows = list(
        conn.execute(
            f"""SELECT w.*,
                   (SELECT group_concat(t.tag, ',')
                      FROM (SELECT tag FROM world_tags
                             WHERE slug = w.slug ORDER BY pos) t) AS tags_csv
                FROM worlds w {clause} ORDER BY {order} LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )
    )
    return rows, total


def _fts_query(q: str) -> str:
    """Turn free text into a safe FTS5 prefix query; FTS5 operators would
    otherwise raise on stray quotes or hyphens."""
    terms = [t for t in "".join(c if c.isalnum() else " " for c in q).split() if t]
    return " AND ".join(f'"{t}"*' for t in terms) if terms else '""'


def get(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM worlds WHERE slug=?", (slug,)).fetchone()


def tags_for(conn: sqlite3.Connection, slug: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT tag FROM world_tags WHERE slug=? ORDER BY pos", (slug,)
        )
    ]


def get_by_world_id(conn: sqlite3.Connection, world_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM worlds WHERE world_id=?", (world_id,)).fetchone()


# --- asset refresh (post-job, doesn't require the md file to have changed) --

def refresh_assets(conn: sqlite3.Connection, slug: str, *, map_status: str | None = None) -> None:
    """Re-stat a world's assets on disk and update just those columns.

    scan()'s incremental skip keys off the markdown file's mtime, so it never
    notices an asset appearing or disappearing on its own (e.g. a map.png a
    background job just wrote). This is the targeted alternative a job calls
    when it changes assets without touching the markdown.
    """
    row = get(conn, slug)
    if row is None:
        return
    md_path = paths.WORLDS_DIR / f"{slug}.md"
    if not md_path.exists():
        return
    w = world_mod.load(md_path)

    has_zip, zip_bytes, zip_mtime = _stat(w.zip_path)
    zip_sha = row["zip_sha256"]
    if has_zip and zip_mtime != row["zip_mtime_ns"]:
        zip_sha = _sha256_file(w.zip_path)
    has_prev, prev_bytes, _ = _stat(w.preview_path)
    has_map, map_bytes, map_mtime = _stat(w.map_path)

    if map_status is None:
        map_status = "ok" if has_map else "missing"

    conn.execute(
        """
        UPDATE worlds SET
          has_zip=?, zip_bytes=?, zip_sha256=?, zip_mtime_ns=?,
          has_preview=?, preview_bytes=?,
          has_map=?, map_bytes=?, map_mtime_ns=?, map_status=?, issues=?
        WHERE slug=?
        """,
        (
            int(has_zip), zip_bytes, zip_sha, zip_mtime,
            int(has_prev), prev_bytes,
            int(has_map), map_bytes, map_mtime, map_status,
            json.dumps(world_mod.validate(w)),
            slug,
        ),
    )
    conn.commit()


# --- background jobs ---------------------------------------------------------

def create_job(conn: sqlite3.Connection, kind: str, target: str, params: dict | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (kind, target, params, status, queued_at) VALUES (?,?,?,?,?)",
        (kind, target, json.dumps(params or {}), "queued", _now()),
    )
    conn.commit()
    return cur.lastrowid


def update_job(conn: sqlite3.Connection, job_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def list_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
    )


def append_log(conn: sqlite3.Connection, job_id: int, stream: str, line: str) -> int:
    seq = conn.execute(
        "SELECT COALESCE(MAX(seq), -1) + 1 FROM job_logs WHERE job_id=?", (job_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO job_logs (job_id, seq, ts, stream, line) VALUES (?,?,?,?,?)",
        (job_id, seq, _now(), stream, line),
    )
    conn.commit()
    return seq


def job_logs(conn: sqlite3.Connection, job_id: int, after_seq: int = -1) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM job_logs WHERE job_id=? AND seq>? ORDER BY seq",
            (job_id, after_seq),
        )
    )


# --- payload hashing (M4) -----------------------------------------------------

def update_payload_hash(
    conn: sqlite3.Connection, slug: str, sha256: str | None, bytes_: int | None, error: str | None
) -> None:
    conn.execute(
        "UPDATE worlds SET payload_sha256=?, payload_bytes=?, payload_hashed_at=?, "
        "payload_error=? WHERE slug=?",
        (sha256, bytes_, _now(), error, slug),
    )
    conn.commit()


def worlds_missing_payload_hash(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    q = "SELECT slug, zip_path FROM worlds WHERE has_zip=1 AND payload_hashed_at IS NULL ORDER BY slug"
    if limit:
        q += f" LIMIT {int(limit)}"
    return list(conn.execute(q))


# --- dupe pairs (M4) -----------------------------------------------------------

def dupes_for_worlds(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Everything score_pairs() needs, in one query."""
    return list(
        conn.execute(
            "SELECT slug, worldname, author, publishdate, norm_name, base_name, "
            "version_token, zip_sha256, payload_sha256 FROM worlds"
        )
    )


def upsert_dupe_pairs(conn: sqlite3.Connection, pairs: Iterable[Any]) -> None:
    """`status` is never overwritten here — dismissals/confirmations survive
    a rescan. Pairs no longer produced by a fresh scan are left in place
    (stale but harmless); `POST /dupes/scan` doesn't delete anything."""
    conn.executemany(
        """
        INSERT INTO dupe_pairs (a_slug, b_slug, reason, score, detail, status, status_at)
        VALUES (?,?,?,?,?, 'new', ?)
        ON CONFLICT(a_slug, b_slug, reason) DO UPDATE SET
          score=excluded.score, detail=excluded.detail
        """,
        [(p.a_slug, p.b_slug, p.reason, p.score, p.detail, _now()) for p in pairs],
    )
    conn.commit()


def list_dupes(conn: sqlite3.Connection, status: str = "") -> list[sqlite3.Row]:
    where = "WHERE d.status=?" if status else ""
    params = (status,) if status else ()
    return list(
        conn.execute(
            f"""
            SELECT d.*, wa.worldname AS a_worldname, wb.worldname AS b_worldname,
                   wa.has_map AS a_has_map, wb.has_map AS b_has_map
            FROM dupe_pairs d
            JOIN worlds wa ON wa.slug = d.a_slug
            JOIN worlds wb ON wb.slug = d.b_slug
            {where}
            ORDER BY d.score DESC, d.a_slug, d.reason
            """,
            params,
        )
    )


def set_dupe_status(
    conn: sqlite3.Connection, a_slug: str, b_slug: str, reason: str, status: str, note: str = ""
) -> bool:
    cur = conn.execute(
        "UPDATE dupe_pairs SET status=?, status_note=?, status_at=? "
        "WHERE a_slug=? AND b_slug=? AND reason=?",
        (status, note, _now(), a_slug, b_slug, reason),
    )
    conn.commit()
    return cur.rowcount > 0


def apply_dismissal_statuses(conn: sqlite3.Connection, dismissals: list[dict]) -> None:
    """Re-applies the committed admin/dupe_dismissals.yaml onto a freshly
    scored (freshly rebuilt) index, so a disposable-DB rebuild doesn't lose
    dismissal decisions that predate this scan."""
    for d in dismissals:
        conn.execute(
            "UPDATE dupe_pairs SET status='dismissed', status_note=?, status_at=? "
            "WHERE a_slug=? AND b_slug=? AND reason=? AND status='new'",
            (d.get("note", ""), d.get("at", _now()), d["a_slug"], d["b_slug"], d["reason"]),
        )
    conn.commit()
