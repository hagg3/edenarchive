"""Browse/search the live Eden game servers and hand a world off into the
existing staged-upload flow. Read-only toward edengame.net — no crawl, no
prefetch: one HTTP request per page load or "load more" click.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...core import edenserver, index
from ...core import world as world_mod
from ...core.importer import NEAR_NAME_CUTOFF
from ..templating import is_htmx, templates

router = APIRouter(prefix="/server")

PAGE_SIZE_HINT = 40  # only used to size "start" advances for browse mode


def _badge(conn, sw: edenserver.ServerWorld) -> tuple[str, str, str]:
    """(badge_kind, slug, label) — '' badge_kind means not in the archive."""
    existing = index.get_by_world_id(conn, sw.id)
    if existing:
        return "archived", existing["slug"], existing["worldname"] or existing["slug"]

    norm = world_mod.normalize_name(sw.name)
    base, _ = world_mod.strip_version(norm)
    for r in conn.execute("SELECT slug, worldname, norm_name, base_name FROM worlds"):
        if not r["norm_name"]:
            continue
        if base and r["base_name"] == base:
            return "possibly archived", r["slug"], r["worldname"] or r["slug"]
        if SequenceMatcher(None, norm, r["norm_name"]).ratio() >= NEAR_NAME_CUTOFF:
            return "possibly archived", r["slug"], r["worldname"] or r["slug"]
    return "", "", ""


def _annotate(conn, worlds: list[edenserver.ServerWorld], srv: edenserver.Server, *, hide_junk: bool, sort: str):
    rows = []
    for sw in worlds:
        badge, badge_slug, badge_label = _badge(conn, sw)
        rows.append({
            "id": sw.id,
            "name": sw.name,
            "timestamp": sw.timestamp,
            "score": edenserver.score_world(sw.name, sw.timestamp),
            "preview_url": edenserver.preview_url(sw.id, srv),
            "badge": badge,
            "badge_slug": badge_slug,
            "badge_label": badge_label,
        })
    if hide_junk:
        rows = [r for r in rows if r["score"] >= 0]
    if sort == "newest":
        rows.sort(key=lambda r: r["timestamp"], reverse=True)
    elif sort == "oldest":
        rows.sort(key=lambda r: r["timestamp"])
    elif sort == "quality":
        rows.sort(key=lambda r: r["score"], reverse=True)
    # "relevance" (default): keep the order the server sent — only meaningful
    # when there's a search query; browse mode has no relevance to preserve.
    return rows


@router.get("")
async def server_page(
    request: Request,
    server: str = "current",
    q: str = "",
    start: int = 0,
    sort: str = "relevance",
    hide_junk: bool = False,
    more: bool = False,
):
    conn = request.app.state.db
    try:
        srv = edenserver.get_server(server)
    except edenserver.EdenServerError:
        raise HTTPException(400, f"unknown server: {server!r}")

    error = None
    worlds: list[edenserver.ServerWorld] = []
    is_search = bool(q.strip())
    try:
        if is_search:
            worlds = edenserver.search(q.strip(), srv)
        else:
            worlds = edenserver.browse(start, srv)
    except Exception as exc:  # noqa: BLE001 — surface any network failure to the page
        error = str(exc)

    rows = _annotate(conn, worlds, srv, hide_junk=hide_junk, sort=sort)
    # No cursor from the server: an empty (or short) page means done browsing.
    next_start = start + len(worlds) if (not is_search and worlds) else None

    ctx = {
        "nav": "server", "server": server, "q": q, "start": start, "sort": sort,
        "hide_junk": hide_junk, "rows": rows, "error": error,
        "is_search": is_search, "next_start": next_start,
    }
    if more:
        tpl = "partials/server_more.html"
    elif is_htmx(request):
        tpl = "partials/server_results.html"
    else:
        tpl = "server.html"
    return templates.TemplateResponse(request, tpl, ctx)


@router.post("/fetch")
async def server_fetch(
    request: Request,
    world_id: str = Form(...),
    name: str = Form(""),
    server: str = Form("current"),
):
    try:
        edenserver.get_server(server)
    except edenserver.EdenServerError:
        raise HTTPException(400, f"unknown server: {server!r}")
    job_id = request.app.state.jobs.enqueue(
        "server_fetch", world_id, {"server": server, "name": name}
    )
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)
