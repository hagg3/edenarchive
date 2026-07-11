from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...core import dupes as dupes_mod
from ...core import index, paths
from ..templating import templates

router = APIRouter()

VALID_STATUSES = {"confirmed_dupe", "confirmed_version", "dismissed"}


def _worlds_for_scoring(conn) -> list[dupes_mod.WorldForDupes]:
    return [
        dupes_mod.WorldForDupes(
            slug=r["slug"], worldname=r["worldname"] or "", author=r["author"] or "",
            publishdate=r["publishdate"] or "", norm_name=r["norm_name"] or "",
            base_name=r["base_name"] or "", version_token=r["version_token"] or "",
            zip_sha256=r["zip_sha256"], payload_sha256=r["payload_sha256"],
        )
        for r in index.dupes_for_worlds(conn)
    ]


@router.get("/dupes")
async def dupe_list(request: Request, status: str = ""):
    conn = request.app.state.db
    pairs = index.list_dupes(conn, status=status)
    unhashed = index.worlds_missing_payload_hash(conn)
    return templates.TemplateResponse(
        request, "dupes.html",
        {
            "pairs": pairs, "status": status,
            "unhashed_count": len(unhashed),
            "nav": "dupes",
        },
    )


@router.post("/dupes/scan")
async def dupe_scan(request: Request):
    conn = request.app.state.db
    worlds = _worlds_for_scoring(conn)
    pairs = dupes_mod.score_pairs(worlds)
    index.upsert_dupe_pairs(conn, pairs)
    dismissals = dupes_mod.load_dismissals(paths.DISMISSALS_FILE)
    index.apply_dismissal_statuses(conn, dismissals)
    return RedirectResponse("/dupes", status_code=303)


@router.post("/dupes/{a_slug}/{b_slug}/{reason}")
async def dupe_set_status(
    request: Request, a_slug: str, b_slug: str, reason: str,
    status: str = Form(...), note: str = Form(""),
):
    if status not in VALID_STATUSES:
        raise HTTPException(400, f"invalid status: {status!r}")
    conn = request.app.state.db
    a, b = sorted((a_slug, b_slug))
    ok = index.set_dupe_status(conn, a, b, reason, status, note)
    if not ok:
        raise HTTPException(404)
    if status == "dismissed":
        dupes_mod.append_dismissal(paths.DISMISSALS_FILE, a, b, reason, note)
    return RedirectResponse("/dupes", status_code=303)


@router.post("/dupes/hash/bulk")
async def hash_bulk(request: Request):
    conn = request.app.state.db
    rows = index.worlds_missing_payload_hash(conn)
    job_ids = [request.app.state.jobs.enqueue("payload_hash", r["slug"]) for r in rows]
    return templates.TemplateResponse(
        request, "partials/hash_bulk_enqueued.html",
        {"count": len(job_ids), "job_ids": job_ids},
    )


@router.post("/dupes/hash/{slug}")
async def hash_one(request: Request, slug: str):
    conn = request.app.state.db
    row = index.get(conn, slug)
    if row is None:
        raise HTTPException(404)
    job_id = request.app.state.jobs.enqueue("payload_hash", slug)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)
