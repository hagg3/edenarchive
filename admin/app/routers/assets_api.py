from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse

from ...core import edenserver, index, paths
from ..templating import is_htmx, templates

router = APIRouter()

PAGE_SIZE = 60
PREVIEW_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@router.get("/assets")
async def asset_grid(
    request: Request,
    status: str = "",
    sort: str = "name",
    page: int = Query(1, ge=1),
):
    conn = request.app.state.db
    asset_filter = {
        "missing_map": "missing_map",
        "missing_preview": "missing_preview",
        "missing_zip": "missing_zip",
    }.get(status, "")
    offset = (page - 1) * PAGE_SIZE
    rows, total = index.search(
        conn, asset=asset_filter, sort=sort, limit=PAGE_SIZE, offset=offset
    )
    too_large = conn.execute(
        "SELECT COUNT(*) FROM worlds WHERE map_status='too_large'"
    ).fetchone()[0]
    ctx = {
        "rows": rows,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)),
        "status": status,
        "sort": sort,
        "too_large": too_large,
        "nav": "assets",
    }
    tpl = "partials/asset_grid.html" if is_htmx(request) else "assets.html"
    return templates.TemplateResponse(request, tpl, ctx)


@router.post("/assets/{world_id}/map")
async def enqueue_map(request: Request, world_id: str):
    conn = request.app.state.db
    row = index.get_by_world_id(conn, world_id)
    if row is None:
        raise HTTPException(404)
    job_id = request.app.state.jobs.enqueue("mapgen", world_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/assets/mapgen/bulk")
async def enqueue_bulk_map(request: Request):
    """Enqueue mapgen for every world currently missing a map, excluding the
    ones already known to be too_large for node-mapgen."""
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT world_id FROM worlds WHERE has_map=0 AND world_id IS NOT NULL "
        "AND map_status != 'too_large'"
    ).fetchall()
    job_ids = [request.app.state.jobs.enqueue("mapgen", r["world_id"]) for r in rows]
    return templates.TemplateResponse(
        request,
        "partials/bulk_enqueued.html",
        {"count": len(job_ids), "job_ids": job_ids},
    )


@router.post("/assets/preview/backfill")
async def enqueue_preview_backfill(request: Request):
    """Bulk-fetch {id}.eden.png previews for every world missing one, from
    the Eden game servers. One job — see jobs.py's _run_preview_backfill for
    why misses there are normal, not failures."""
    job_id = request.app.state.jobs.enqueue("preview_backfill", "all")
    return templates.TemplateResponse(
        request, "partials/bulk_enqueued.html",
        {"count": 1, "job_ids": [job_id], "label": "preview backfill"},
    )


@router.post("/assets/{world_id}/preview")
async def upload_preview(request: Request, world_id: str, file: UploadFile):
    conn = request.app.state.db
    row = index.get_by_world_id(conn, world_id)
    if row is None:
        raise HTTPException(404)

    suffix = ("." + file.filename.rsplit(".", 1)[-1].lower()) if "." in (file.filename or "") else ""
    if suffix not in PREVIEW_EXTS:
        raise HTTPException(400, f"unsupported image type: {suffix or 'unknown'}")

    dest_dir = paths.asset_dir_for(world_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = paths.assert_writable(dest_dir / f"{world_id}.eden.png")
    data = await file.read()
    dest.write_bytes(data)

    index.refresh_assets(conn, row["slug"])
    return RedirectResponse(f"/worlds/{row['slug']}", status_code=303)


@router.post("/assets/{world_id}/preview/fetch")
async def refetch_preview(request: Request, world_id: str):
    conn = request.app.state.db
    row = index.get_by_world_id(conn, world_id)
    if row is None:
        raise HTTPException(404)

    dest_dir = paths.asset_dir_for(world_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = paths.assert_writable(dest_dir / f"{world_id}.eden.png")

    data, server = edenserver.fetch_preview_any(world_id)
    if data is None:
        return templates.TemplateResponse(
            request, "partials/preview_fetch_result.html",
            {"ok": False, "error": "not found on either server", "world_id": world_id},
        )
    dest.write_bytes(data)

    index.refresh_assets(conn, row["slug"])
    return templates.TemplateResponse(
        request, "partials/preview_fetch_result.html",
        {"ok": True, "world_id": world_id, "server": server},
    )
