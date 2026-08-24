"""ThreadingHTTPServer serving the JSON API + the static web/ frontend.

Bound to 127.0.0.1 only — this is a local archivist tool, not a public
service. /api/preview honours the rate discipline noted in
edenarchive/admin/core/edenserver.py:8: exactly one HTTP request per user
action, cached to disk, never prefetched or polled.
"""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import classify, liveserver
from .query import DEFAULT_EXCLUDE_FLAGS, BadRegex, SearchParams, search

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"
PREVIEW_CACHE_DIR = ROOT / ".preview_cache"
PREVIEW_HOST = "files.edengame.net"  # see CLAUDE.md: legacy host, per the plan;
# the current client (ShareUtil.mm) points at files2.edengame.net instead.

DB_PATH = ROOT / "worlds.db"

LIVE_RECENT_PAGE_CAP = 30
LIVE_SEARCH_RESULT_CAP = 300

# Process-lifetime memo of the full featured list per server — not a TTL
# cache, not persisted; just avoids re-hitting the server every time the
# archivist flips back to the Featured tab in one session. Cleared only by
# an explicit "Refresh" (?refresh=1) or a process restart.
_featured_cache: dict[str, list[dict]] = {}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _json(handler: "Handler", status: int, payload) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _bool(v: str | None) -> bool:
    return v is not None and v.lower() in ("1", "true", "yes", "on")


def _params_from_query(qs: dict) -> SearchParams:
    def one(name, default=None):
        return qs.get(name, [default])[0]

    flags_require = [f for f in qs.get("flag_require", []) if f]
    flags_exclude = [f for f in qs.get("flag_exclude", []) if f]
    if "flag_exclude" not in qs and "flag_require" not in qs:
        flags_exclude = list(DEFAULT_EXCLUDE_FLAGS)

    return SearchParams(
        q=one("q", ""),
        mode=one("mode", "lexical"),
        date_from=one("from"),
        date_to=one("to"),
        name_contains=one("name_contains"),
        name_excludes=one("name_excludes"),
        origin=one("origin"),
        origin_class=one("origin_class"),
        author=one("author"),
        flag_require=flags_require,
        flag_exclude=flags_exclude,
        min_quality=float(one("min_quality")) if one("min_quality") else None,
        min_series_size=int(one("min_series_size")) if one("min_series_size") else None,
        series_pos=one("series_pos"),
        featured_only=_bool(one("featured_only")),
        collapse=one("collapse", "none"),
        sort=one("sort", "relevance"),
        limit=min(int(one("limit", "200")), 2000),
        offset=int(one("offset", "0")),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "EdenFind/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        path = parsed.path

        try:
            if path == "/api/stats":
                return self.handle_stats()
            if path == "/api/search":
                return self.handle_search(qs)
            m = re.match(r"^/api/world/(\d+)$", path)
            if m:
                return self.handle_world(int(m.group(1)))
            m = re.match(r"^/api/series/(\d+)$", path)
            if m:
                return self.handle_series(int(m.group(1)))
            m = re.match(r"^/api/preview/(\d+)$", path)
            if m:
                return self.handle_preview(int(m.group(1)))
            if path == "/api/export":
                return self.handle_export(qs)
            if path == "/api/live/recent":
                return self.handle_live_recent(qs)
            if path == "/api/live/search":
                return self.handle_live_search(qs)
            if path == "/api/live/featured":
                return self.handle_live_featured(qs)
            m = re.match(r"^/api/live/preview/(\d+)$", path)
            if m:
                return self.handle_live_preview(m.group(1), qs)
            if path == "/api/live/saved":
                return self.handle_live_saved_list()
            return self.handle_static(path)
        except BadRegex as e:
            return _json(self, 400, {"error": f"bad regex: {e}"})
        except Exception as e:  # noqa: BLE001
            self.log_message("error: %s", e)
            return _json(self, 500, {"error": str(e)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return _json(self, 400, {"error": "bad json"})
        if parsed.path == "/api/triage":
            return self.handle_triage_post(payload)
        if parsed.path == "/api/live/save":
            return self.handle_live_save(payload)
        if parsed.path == "/api/live/unsave":
            return self.handle_live_unsave(payload)
        return _json(self, 404, {"error": "not found"})

    # ---- handlers ---------------------------------------------------------

    def handle_stats(self) -> None:
        conn = _get_conn()
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        total = conn.execute("SELECT COUNT(*) FROM worlds").fetchone()[0]
        distinct_names = conn.execute("SELECT COUNT(*) FROM distinct_names").fetchone()[0]
        date_range = conn.execute("SELECT MIN(iso_date), MAX(iso_date) FROM worlds").fetchone()
        pre2015 = conn.execute(
            "SELECT COUNT(*) FROM worlds WHERE iso_date < '2015-01-01' AND source = 'filelist'"
        ).fetchone()[0]
        pre_gap = conn.execute(
            "SELECT COUNT(*) FROM worlds WHERE iso_date < '2015-02-01'"
        ).fetchone()[0]
        featured_total = conn.execute("SELECT COUNT(DISTINCT world_id) FROM featured").fetchone()[0]
        rejects = conn.execute("SELECT COUNT(*) FROM rejects").fetchone()[0]
        flag_counts = {}
        for name, bit in classify.FLAG_BITS.items():
            n = conn.execute(
                "SELECT COUNT(*) FROM worlds WHERE (flags & ?) != 0", (1 << bit,)
            ).fetchone()[0]
            flag_counts[name] = n
        conn.close()
        _json(
            self,
            200,
            {
                "total_rows": total,
                "distinct_names": distinct_names,
                "date_min": date_range[0],
                "date_max": date_range[1],
                "pre_2015_rows": pre2015,
                "coverage_gap_end": "2015-02-01",
                "coverage_gap_rows": pre_gap,
                "coverage_warning": (
                    f"Only {pre2015} log rows predate 2015 at all — the upload log was "
                    "rebuilt/restarted around February 2015. Coverage before then comes "
                    "almost entirely from the featured/ snapshots, not the upload log."
                ),
                "featured_distinct_worlds": featured_total,
                "reject_count": rejects,
                "flag_counts": flag_counts,
                "built_at": meta.get("built_at"),
            },
        )

    def handle_search(self, qs: dict) -> None:
        params = _params_from_query(qs)
        conn = _get_conn()
        result = search(conn, params)
        conn.close()
        _json(self, 200, result)

    def handle_world(self, world_id: int) -> None:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM worlds WHERE id = ?", (world_id,)).fetchone()
        if not row:
            conn.close()
            return _json(self, 404, {"error": "not found"})
        d = dict(row)
        d["flag_names"] = classify.flags_list(d["flags"])
        d["score_parts"] = json.loads(d["score_parts"])

        triage = conn.execute(
            "SELECT status, note, updated_at FROM triage WHERE world_id = ?", (world_id,)
        ).fetchone()
        d["triage"] = dict(triage) if triage else {"status": "none", "note": None}

        series_siblings = []
        if d["series_id"] is not None:
            series_siblings = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, ts, iso_date, name, version_ordinal, quality_score "
                    "FROM worlds WHERE series_id = ? ORDER BY version_ordinal IS NULL, "
                    "version_ordinal, ts",
                    (d["series_id"],),
                ).fetchall()
            ]

        similar_names = self._similar_names(conn, d["name_lc"])

        session_neighbours = []
        if d["origin"]:
            session_neighbours = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, ts, iso_date, name, quality_score FROM worlds "
                    "WHERE origin = ? AND ts BETWEEN ? AND ? AND id != ? "
                    "ORDER BY ts LIMIT 200",
                    (d["origin"], d["ts"] - 3600, d["ts"] + 3600, world_id),
                ).fetchall()
            ]

        featured_appearances = [
            dict(r)
            for r in conn.execute(
                "SELECT snapshot_date, rank, name_at_time FROM featured WHERE world_id = ? "
                "ORDER BY snapshot_date",
                (world_id,),
            ).fetchall()
        ]

        conn.close()
        d["series_siblings"] = series_siblings
        d["similar_names"] = similar_names
        d["session_neighbours"] = session_neighbours
        d["featured_appearances"] = featured_appearances
        _json(self, 200, d)

    def _similar_names(self, conn: sqlite3.Connection, name_lc: str, limit: int = 15):
        grams = [
            f"{('  ' + name_lc + ' ')[i:i+3]}" for i in range(len(name_lc) + 1)
        ]
        if not grams:
            return []
        ph = ",".join("?" for _ in grams)
        rows = conn.execute(
            f"SELECT name_id, COUNT(*) as shared FROM name_ngrams WHERE gram IN ({ph}) "
            f"GROUP BY name_id ORDER BY shared DESC LIMIT 50",
            grams,
        ).fetchall()
        import difflib

        out = []
        for name_id, _ in rows:
            other = conn.execute(
                "SELECT name_lc FROM distinct_names WHERE id = ?", (name_id,)
            ).fetchone()
            if not other or other[0] == name_lc:
                continue
            ratio = difflib.SequenceMatcher(None, name_lc, other[0]).ratio()
            if ratio >= 0.6:
                out.append((ratio, other[0]))
        out.sort(key=lambda x: -x[0])
        return [{"name_lc": n, "ratio": round(r, 3)} for r, n in out[:limit]]

    def handle_series(self, series_id: int) -> None:
        conn = _get_conn()
        srow = conn.execute("SELECT * FROM series WHERE series_id = ?", (series_id,)).fetchone()
        if not srow:
            conn.close()
            return _json(self, 404, {"error": "not found"})
        members = [
            dict(r)
            for r in conn.execute(
                "SELECT id, ts, iso_date, name, version_ordinal, quality_score, flags "
                "FROM worlds WHERE series_id = ? ORDER BY version_ordinal IS NULL, "
                "version_ordinal, ts",
                (series_id,),
            ).fetchall()
        ]
        conn.close()
        d = dict(srow)
        d["members"] = members
        _json(self, 200, d)

    def handle_preview(self, ts: int) -> None:
        PREVIEW_CACHE_DIR.mkdir(exist_ok=True)
        cache_path = PREVIEW_CACHE_DIR / f"{ts}.png"
        miss_marker = PREVIEW_CACHE_DIR / f"{ts}.missing"
        if cache_path.exists():
            data = cache_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if miss_marker.exists():
            return _json(self, 404, {"error": "no preview available for this world"})

        url = f"http://{PREVIEW_HOST}/{ts}.eden.png"
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = resp.read()
        except (urllib.error.URLError, TimeoutError) as e:
            miss_marker.write_text(str(e))
            return _json(self, 404, {"error": "no preview available for this world"})

        cache_path.write_bytes(data)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_triage_post(self, payload: dict) -> None:
        world_id = payload.get("id")
        status = payload.get("status", "none")
        # Distinguish "note omitted" (star/reject toggle from the table —
        # leave any existing note alone) from "note explicitly sent" (the
        # drawer's note field, which may legitimately be set to "").
        note_provided = "note" in payload
        note = payload.get("note")
        if world_id is None or status not in ("star", "reject", "none"):
            return _json(self, 400, {"error": "expected {id, status: star|reject|none, note?}"})
        conn = sqlite3.connect(DB_PATH)
        now = datetime.now(timezone.utc).isoformat()
        if note_provided:
            conn.execute(
                "INSERT INTO triage (world_id, status, note, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(world_id) DO UPDATE SET status=excluded.status, "
                "note=excluded.note, updated_at=excluded.updated_at",
                (world_id, status, note, now),
            )
        else:
            conn.execute(
                "INSERT INTO triage (world_id, status, note, updated_at) VALUES (?,?,NULL,?) "
                "ON CONFLICT(world_id) DO UPDATE SET status=excluded.status, "
                "updated_at=excluded.updated_at",
                (world_id, status, now),
            )
        conn.commit()
        conn.close()
        _json(self, 200, {"ok": True})

    # ---- live server browsing ---------------------------------------------
    # Every handler below makes at most one outbound request to the game
    # server per call, triggered only by an explicit user action in the UI
    # (a button click / query submit) — never looped, prefetched, or polled.
    # See edenfind/liveserver.py's module docstring for the same rule stated
    # at the protocol layer.

    def handle_live_recent(self, qs: dict) -> None:
        name = qs.get("server", ["current"])[0]
        try:
            server = liveserver.get_server(name)
        except liveserver.LiveServerError as e:
            return _json(self, 400, {"error": str(e)})
        start = int(qs.get("start", ["0"])[0])
        try:
            rows = liveserver.browse(start, server)
        except liveserver.LiveServerError as e:
            return _json(self, 502, {"error": str(e)})
        rows = rows[:LIVE_RECENT_PAGE_CAP]
        _json(
            self,
            200,
            {
                "server": name,
                "rows": [{"ts": r.ts, "name": r.name} for r in rows],
                "next_start": start + len(rows),
                "has_more": len(rows) == LIVE_RECENT_PAGE_CAP,
            },
        )

    def handle_live_search(self, qs: dict) -> None:
        name = qs.get("server", ["current"])[0]
        q = qs.get("q", [""])[0].strip()
        try:
            server = liveserver.get_server(name)
        except liveserver.LiveServerError as e:
            return _json(self, 400, {"error": str(e)})
        if not q:
            return _json(self, 200, {"server": name, "rows": [], "capped": False})
        try:
            rows = liveserver.search(q, server)
        except liveserver.LiveServerError as e:
            return _json(self, 502, {"error": str(e)})
        capped = len(rows) > LIVE_SEARCH_RESULT_CAP
        rows = rows[:LIVE_SEARCH_RESULT_CAP]
        _json(
            self,
            200,
            {
                "server": name,
                "rows": [{"ts": r.ts, "name": r.name} for r in rows],
                "capped": capped,
            },
        )

    def handle_live_featured(self, qs: dict) -> None:
        name = qs.get("server", ["current"])[0]
        try:
            server = liveserver.get_server(name)
        except liveserver.LiveServerError as e:
            return _json(self, 400, {"error": str(e)})
        refresh = _bool(qs.get("refresh", [None])[0])
        if refresh or name not in _featured_cache:
            try:
                entries = liveserver.fetch_featured(server)
            except liveserver.LiveServerError as e:
                return _json(self, 502, {"error": str(e)})
            _featured_cache[name] = [
                {"ts": e.ts, "name": e.name, "rank": e.rank} for e in entries
            ]
        _json(self, 200, {"server": name, "rows": _featured_cache[name]})

    def handle_live_preview(self, ts: str, qs: dict) -> None:
        name = qs.get("server", ["current"])[0]
        try:
            server = liveserver.get_server(name)
        except liveserver.LiveServerError as e:
            return _json(self, 400, {"error": str(e)})
        PREVIEW_CACHE_DIR.mkdir(exist_ok=True)
        cache_path = PREVIEW_CACHE_DIR / f"{ts}_{name}.png"
        miss_marker = PREVIEW_CACHE_DIR / f"{ts}_{name}.missing"
        if cache_path.exists():
            data = cache_path.read_bytes()
        elif miss_marker.exists():
            return _json(self, 404, {"error": "no preview available for this world"})
        else:
            data = liveserver.fetch_preview_bytes(ts, server)
            if data is None:
                miss_marker.write_text("miss")
                return _json(self, 404, {"error": "no preview available for this world"})
            cache_path.write_bytes(data)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_live_saved_list(self) -> None:
        conn = _get_conn()
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT ts, server, name, note, saved_at FROM live_saved "
                "ORDER BY saved_at DESC"
            ).fetchall()
        ]
        conn.close()
        _json(self, 200, {"rows": rows})

    def handle_live_save(self, payload: dict) -> None:
        ts = payload.get("ts")
        server = payload.get("server")
        name = payload.get("name")
        note = payload.get("note")
        if ts is None or server not in liveserver.SERVERS or not name:
            return _json(self, 400, {"error": "expected {ts, server, name, note?}"})
        conn = sqlite3.connect(DB_PATH)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO live_saved (ts, server, name, note, saved_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(ts, server) DO UPDATE SET name=excluded.name, "
            "note=excluded.note, saved_at=excluded.saved_at",
            (ts, server, name, note, now),
        )
        conn.commit()
        conn.close()
        _json(self, 200, {"ok": True})

    def handle_live_unsave(self, payload: dict) -> None:
        ts = payload.get("ts")
        server = payload.get("server")
        if ts is None or server is None:
            return _json(self, 400, {"error": "expected {ts, server}"})
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM live_saved WHERE ts = ? AND server = ?", (ts, server))
        conn.commit()
        conn.close()
        _json(self, 200, {"ok": True})

    def handle_export(self, qs: dict) -> None:
        fmt = qs.get("format", ["csv"])[0]
        starred_only = _bool(qs.get("starred", [None])[0])
        conn = _get_conn()
        if starred_only:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT worlds.id, worlds.ts, worlds.iso_date, worlds.name, "
                    "worlds.quality_score, triage.status, triage.note FROM worlds "
                    "JOIN triage ON triage.world_id = worlds.id WHERE triage.status != 'none'"
                ).fetchall()
            ]
        else:
            params = _params_from_query(qs)
            params.limit = 100000
            params.offset = 0
            rows = search(conn, params)["rows"]
        conn.close()

        if fmt == "ids":
            body = json.dumps([r["id"] for r in rows]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if fmt == "json":
            body = json.dumps(rows, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", "attachment; filename=edenfind_export.json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        body = buf.getvalue().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", "attachment; filename=edenfind_export.csv")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        rel = path.lstrip("/")
        fpath = (WEB_DIR / rel).resolve()
        if WEB_DIR not in fpath.parents and fpath != WEB_DIR:
            return _json(self, 403, {"error": "forbidden"})
        if not fpath.exists() or not fpath.is_file():
            return _json(self, 404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
        data = fpath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    if not DB_PATH.exists():
        sys.exit(f"error: {DB_PATH} not found — run `python3 build.py` first")
    port = 8777
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"EdenFind serving on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
