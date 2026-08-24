"""Four search backends over one shared filter pipeline.

Mode and filters are orthogonal: each mode returns a candidate id set (or
None, meaning "no restriction" — used for empty-query browsing), then the
same SQL filter stage applies. Adding a mode later (including embeddings)
means adding one candidate generator function.
"""
from __future__ import annotations

import difflib
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from . import classify, terms

DEFAULT_EXCLUDE_FLAGS = ["f_chat_channel", "f_chat_words", "f_default", "f_repost", "f_flood"]

_FUZZY_CANDIDATE_NAMES = 200
_FUZZY_MIN_RATIO = 0.45


def _trigrams(s: str) -> set[str]:
    s = f"  {s} "
    return {s[i : i + 3] for i in range(len(s) - 2)}


@dataclass
class SearchParams:
    q: str = ""
    mode: str = "lexical"  # lexical | fuzzy | concept | regex
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    name_contains: Optional[str] = None
    name_excludes: Optional[str] = None
    origin: Optional[str] = None
    origin_class: Optional[str] = None
    author: Optional[str] = None
    flag_require: list[str] = field(default_factory=list)
    flag_exclude: list[str] = field(default_factory=list)
    min_quality: Optional[float] = None
    min_series_size: Optional[int] = None
    series_pos: Optional[str] = None  # 'first' | 'last'
    featured_only: bool = False
    collapse: str = "none"  # none | name | series
    sort: str = "relevance"  # relevance | date_desc | date_asc | quality_desc
    limit: int = 200
    offset: int = 0

    @classmethod
    def default_preset(cls, **overrides) -> "SearchParams":
        p = cls(flag_exclude=list(DEFAULT_EXCLUDE_FLAGS))
        for k, v in overrides.items():
            setattr(p, k, v)
        return p


class BadRegex(ValueError):
    pass


# ---------------------------------------------------------------------------
# Candidate generators — each returns (ordered_ids, score_by_id) or None.
# ---------------------------------------------------------------------------


def _fts_escape(q: str) -> str:
    q = q.strip()
    if not q:
        return q
    # If the user already wrote FTS syntax (quotes, boolean ops, prefix*),
    # trust it. Otherwise treat the query as an implicit AND of terms so
    # "cmg airport" doesn't degrade to an OR across all of FTS5's defaults.
    if any(c in q for c in ('"', "*")) or re.search(
        r"\b(AND|OR|NOT)\b", q
    ):
        return q
    terms_ = re.findall(r"[A-Za-z0-9']+", q)
    return " AND ".join(terms_) if terms_ else q


def _fts_match_expr(mode: str, q: str) -> Optional[str]:
    """Returns the FTS5 MATCH expression for lexical/concept modes, or None
    if there's no query text to search on."""
    ql = q.strip().lower()
    if not ql:
        return None
    if mode == "concept":
        expansions: set[str] = set()
        for concept, words in terms.CONCEPT_MAP.items():
            if concept in ql or ql in concept:
                expansions.update(words)
        if expansions:
            or_terms = set(re.findall(r"[A-Za-z0-9']+", ql)) | expansions
            return " OR ".join(sorted(or_terms))
    return _fts_escape(q)


def _candidates_fuzzy(conn: sqlite3.Connection, q: str, limit: int):
    ql = q.strip().lower()
    if not ql:
        return None
    grams = list(_trigrams(ql))
    if not grams:
        return [], {}
    placeholders = ",".join("?" for _ in grams)
    rows = conn.execute(
        f"SELECT name_id, COUNT(*) as shared FROM name_ngrams WHERE gram IN ({placeholders}) "
        f"GROUP BY name_id ORDER BY shared DESC LIMIT ?",
        (*grams, _FUZZY_CANDIDATE_NAMES * 3),
    ).fetchall()
    if not rows:
        return [], {}
    name_ids = [r[0] for r in rows]
    ph2 = ",".join("?" for _ in name_ids)
    name_rows = conn.execute(
        f"SELECT id, name_lc FROM distinct_names WHERE id IN ({ph2})", name_ids
    ).fetchall()
    scored_names = []
    for name_id, name_lc in name_rows:
        ratio = difflib.SequenceMatcher(None, ql, name_lc).ratio()
        if ratio >= _FUZZY_MIN_RATIO:
            scored_names.append((ratio, name_lc))
    scored_names.sort(key=lambda x: -x[0])
    scored_names = scored_names[:_FUZZY_CANDIDATE_NAMES]

    if not scored_names:
        return [], {}
    ratio_by_name_lc = {name_lc: ratio for ratio, name_lc in scored_names}
    ph3 = ",".join("?" for _ in scored_names)
    world_rows = conn.execute(
        f"SELECT id, name_lc FROM worlds WHERE name_lc IN ({ph3})",
        list(ratio_by_name_lc),
    ).fetchall()
    # Preserve fuzzy rank order (best match first), independent of the
    # arbitrary row order SQLite returns for the IN(...) lookup.
    world_rows.sort(key=lambda r: -ratio_by_name_lc[r[1]])
    ids: list[int] = []
    scores: dict[int, float] = {}
    for wid, name_lc in world_rows:
        ids.append(wid)
        scores[wid] = ratio_by_name_lc[name_lc]
        if len(ids) >= limit:
            break
    return ids, scores


def _regex_matched_name_lc(conn: sqlite3.Connection, q: str) -> list[str]:
    """Runs the pattern over the 339k *distinct* names once (not every row —
    that's what makes this fast enough to be interactive) and returns every
    matching name_lc. Unlike fuzzy, this isn't a top-N heuristic mode, so the
    match set is returned in full for an accurate total/count."""
    try:
        pattern = re.compile(q, re.IGNORECASE)
    except re.error as e:
        raise BadRegex(str(e))
    return [
        name_lc
        for (name_lc,) in conn.execute("SELECT name_lc FROM distinct_names")
        if pattern.search(name_lc)
    ]


_CANDIDATE_MODES = {
    "fuzzy": _candidates_fuzzy,
}


# ---------------------------------------------------------------------------
# Shared filter pipeline
# ---------------------------------------------------------------------------


def _flag_mask(names: list[str]) -> int:
    mask = 0
    for n in names:
        if n in classify.FLAG_BITS:
            mask |= 1 << classify.FLAG_BITS[n]
    return mask


def _build_where(
    params: SearchParams,
    candidate_ids: Optional[list[int]] = None,
    name_lc_in: Optional[list[str]] = None,
):
    clauses = []
    args: list = []

    if candidate_ids is not None:
        if not candidate_ids:
            return "0", []
        placeholders = ",".join("?" for _ in candidate_ids)
        clauses.append(f"worlds.id IN ({placeholders})")
        args.extend(candidate_ids)

    if name_lc_in is not None:
        if not name_lc_in:
            return "0", []
        placeholders = ",".join("?" for _ in name_lc_in)
        clauses.append(f"worlds.name_lc IN ({placeholders})")
        args.extend(name_lc_in)

    if params.date_from:
        clauses.append("worlds.iso_date >= ?")
        args.append(params.date_from)
    if params.date_to:
        clauses.append("worlds.iso_date <= ?")
        args.append(params.date_to)
    if params.name_contains:
        clauses.append("worlds.name_lc LIKE ?")
        args.append(f"%{params.name_contains.lower()}%")
    if params.name_excludes:
        clauses.append("worlds.name_lc NOT LIKE ?")
        args.append(f"%{params.name_excludes.lower()}%")
    if params.origin:
        clauses.append("worlds.origin = ?")
        args.append(params.origin)
    if params.origin_class:
        clauses.append("origins.origin_class = ?")
        args.append(params.origin_class)
    if params.author:
        clauses.append("worlds.author LIKE ?")
        args.append(f"%{params.author}%")
    if params.flag_require:
        mask = _flag_mask(params.flag_require)
        clauses.append("(worlds.flags & ?) = ?")
        args.extend([mask, mask])
    if params.flag_exclude:
        mask = _flag_mask(params.flag_exclude)
        clauses.append("(worlds.flags & ?) = 0")
        args.append(mask)
    if params.min_quality is not None:
        clauses.append("worlds.quality_score >= ?")
        args.append(params.min_quality)
    if params.min_series_size is not None:
        clauses.append("series.size >= ?")
        args.append(params.min_series_size)
    if params.series_pos == "first":
        clauses.append("worlds.ts = series.first_ts")
    elif params.series_pos == "last":
        clauses.append("worlds.ts = series.last_ts")
    if params.featured_only:
        mask = 1 << classify.FLAG_BITS["f_featured"]
        clauses.append("(worlds.flags & ?) != 0")
        args.append(mask)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, args


_BASE_FROM = (
    "worlds LEFT JOIN origins ON worlds.origin = origins.origin "
    "LEFT JOIN series ON worlds.series_id = series.series_id"
)

_ROW_COLUMNS = (
    "worlds.id, worlds.ts, worlds.iso_date, worlds.name, worlds.origin, "
    "worlds.origin_kind, worlds.source, worlds.series_id, worlds.version_ordinal, "
    "worlds.author, worlds.chat_channel, worlds.quality_score, worlds.flags, "
    "origins.origin_class, series.size as series_size"
)
# Unqualified names for reading a derived (sub-query) result set, where the
# "worlds."/"origins."/"series." table qualifiers no longer resolve.
_ROW_COLUMN_NAMES = [c.split(" as ")[-1].split(".")[-1] for c in _ROW_COLUMNS.split(", ")]
_ROW_COLUMN_NAMES_SQL = ", ".join(_ROW_COLUMN_NAMES)

_SORT_SQL = {
    "date_desc": "worlds.ts DESC",
    "date_asc": "worlds.ts ASC",
    "quality_desc": "worlds.quality_score DESC",
}


def _collapse_col(params: SearchParams) -> Optional[str]:
    if params.collapse == "name":
        return "worlds.name_lc"
    if params.collapse == "series":
        return "COALESCE(worlds.series_id, -worlds.id)"
    return None


def _collapse_col_unqualified(params: SearchParams) -> Optional[str]:
    """Same partition key as _collapse_col, expressed in terms of the
    unqualified output columns available once nested in a derived table."""
    if params.collapse == "name":
        return "LOWER(name)"
    if params.collapse == "series":
        return "COALESCE(series_id, -id)"
    return None


def _split_order(order_sql: str) -> tuple[str, str]:
    """order_sql is a full ORDER BY clause fragment ("worlds.ts DESC", or a
    bare bm25/CASE expression with no direction, meaning "smaller is
    better"). Splits it into a standalone expression (legal in a SELECT
    list) and its direction, since "expr DESC" is not itself a valid
    expression and can't be aliased as one."""
    stripped = order_sql.strip()
    upper = stripped.upper()
    if upper.endswith(" DESC"):
        return stripped[: -len(" DESC")], "DESC"
    if upper.endswith(" ASC"):
        return stripped[: -len(" ASC")], "ASC"
    return stripped, "ASC"


def _run(conn, from_sql, where, args, params, order_sql, out_of_band_scores=None):
    collapse_col = _collapse_col(params)
    if collapse_col:
        # order_sql may reference things only valid in the innermost FROM
        # scope (worlds_fts's bm25(), which SQLite refuses to combine with a
        # window function in the same SELECT list) — compute it in its own
        # layer first, rank in a second layer over the unqualified result
        # (where "worlds."/"origins."/"series." no longer resolve), then
        # filter/sort in a third.
        expr, direction = _split_order(order_sql)
        collapse_col_uq = _collapse_col_unqualified(params)
        sql = (
            f"SELECT {_ROW_COLUMN_NAMES_SQL} FROM ("
            f"SELECT {_ROW_COLUMN_NAMES_SQL}, _rel, ROW_NUMBER() OVER ("
            f"PARTITION BY {collapse_col_uq} ORDER BY quality_score DESC, ts DESC"
            f") as rn FROM ("
            f"SELECT {_ROW_COLUMNS}, ({expr}) as _rel FROM {from_sql} WHERE {where}"
            f")"
            f") WHERE rn = 1 ORDER BY _rel {direction}"
        )
        count_sql = f"SELECT COUNT(*) FROM (SELECT DISTINCT {collapse_col} FROM {from_sql} WHERE {where})"
    else:
        sql = f"SELECT {_ROW_COLUMNS} FROM {from_sql} WHERE {where} ORDER BY {order_sql}"
        count_sql = f"SELECT COUNT(*) FROM {from_sql} WHERE {where}"

    total = conn.execute(count_sql, args).fetchone()[0]
    sql += " LIMIT ? OFFSET ?"
    rows = conn.execute(sql, (*args, params.limit, params.offset)).fetchall()

    out_rows = []
    for r in rows:
        d = dict(zip(_ROW_COLUMN_NAMES, r))
        d["flag_names"] = classify.flags_list(d["flags"])
        d["relevance"] = (out_of_band_scores or {}).get(d["id"])
        out_rows.append(d)
    return {"total": total, "rows": out_rows, "offset": params.offset, "limit": params.limit}


def search(conn: sqlite3.Connection, params: SearchParams) -> dict:
    order_sql = _SORT_SQL.get(params.sort, "worlds.ts DESC")

    if params.mode in ("lexical", "concept"):
        fts_expr = _fts_match_expr(params.mode, params.q)
        if fts_expr is None:
            where, args = _build_where(params, None)
            return _run(conn, _BASE_FROM, where, args, params, order_sql)

        from_sql = f"worlds_fts JOIN ({_BASE_FROM}) ON worlds.id = worlds_fts.rowid"
        where, args = _build_where(params, None)
        where = f"worlds_fts MATCH ? AND ({where})"
        args = [fts_expr, *args]
        if params.sort == "relevance":
            # bm25 is lower-is-better and, being length-normalized, has a
            # strong bias toward short single-term documents ("Airport")
            # over more descriptive ones ("cmg internatonal airport"). A
            # small quality nudge breaks that bias without overriding text
            # relevance for genuinely different matches.
            order_sql = "bm25(worlds_fts) - (worlds.quality_score * 0.08)"
        return _run(conn, from_sql, where, args, params, order_sql)

    if params.mode in _CANDIDATE_MODES and params.q.strip():
        gen = _CANDIDATE_MODES[params.mode]
        candidate_limit = max(params.limit + params.offset, 1000)
        candidate_ids, rel_scores = gen(conn, params.q, candidate_limit)
        where, args = _build_where(params, candidate_ids)
        if params.sort == "relevance":
            # Candidate order already encodes relevance; CASE-order by it in
            # SQL so pagination/collapse stay correct without a Python pass
            # over a potentially large filtered set.
            rank_case = " ".join(
                f"WHEN {wid} THEN {i}" for i, wid in enumerate(candidate_ids)
            )
            order_sql = (
                f"(CASE worlds.id {rank_case} ELSE {len(candidate_ids)} END)"
                if candidate_ids
                else "worlds.ts DESC"
            )
        return _run(conn, _BASE_FROM, where, args, params, order_sql, rel_scores)

    if params.mode == "regex" and params.q.strip():
        matched_name_lc = _regex_matched_name_lc(conn, params.q)
        where, args = _build_where(params, name_lc_in=matched_name_lc)
        if params.sort == "relevance":
            order_sql = "worlds.ts DESC"
        return _run(conn, _BASE_FROM, where, args, params, order_sql)

    # No query text: plain browse over the filters.
    where, args = _build_where(params, None)
    return _run(conn, _BASE_FROM, where, args, params, order_sql)
