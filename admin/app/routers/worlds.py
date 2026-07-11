from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, Request

from ...core import git, index, paths
from ...core import world as world_mod
from ..templating import is_htmx, templates

router = APIRouter()

PAGE_SIZE = 60


def _split_tags(raw: str) -> list[str]:
    """Comma-separated editor input -> an ordered, de-duplicated tag list."""
    out: list[str] = []
    for t in raw.split(","):
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out


@router.get("/worlds")
async def list_worlds(
    request: Request,
    q: str = "",
    tag: str = "",
    author: str = "",
    asset: str = "",
    issue: str = "",
    sort: str = "name",
    page: int = Query(1, ge=1),
):
    conn = request.app.state.db
    offset = (page - 1) * PAGE_SIZE
    rows, total = index.search(
        conn,
        q=q,
        tag=tag,
        author=author,
        asset=asset,
        issue=issue,
        sort=sort,
        limit=PAGE_SIZE,
        offset=offset,
    )
    ctx = {
        "rows": rows,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // PAGE_SIZE)),
        "q": q,
        "tag": tag,
        "author": author,
        "asset": asset,
        "issue": issue,
        "sort": sort,
        "tags": index.all_tags(conn),
        "authors": index.all_authors(conn),
        "issue_kinds": sorted(index.issue_tallies(conn)),
        "nav": "worlds",
    }
    # HTMX asks for just the table; a normal navigation gets the whole page.
    tpl = "partials/world_table.html" if is_htmx(request) else "worlds.html"
    return templates.TemplateResponse(request, tpl, ctx)


def _detail_ctx(request: Request, slug: str, *, saved: bool = False, error: str = "") -> dict:
    conn = request.app.state.db
    row = index.get(conn, slug)
    if row is None:
        raise HTTPException(404)

    md_path = paths.world_md_for(slug)
    w = world_mod.load(md_path)

    return {
        "row": row,
        "w": w,
        "tags": index.tags_for(conn, slug),
        "all_tags": index.all_tags(conn),
        "rel_path": str(md_path.relative_to(paths.REPO_ROOT)),
        "nav": "worlds",
        "saved": saved,
        "error": error,
    }


@router.get("/worlds/{slug}")
async def world_detail(request: Request, slug: str):
    return templates.TemplateResponse(
        request, "world_detail.html", _detail_ctx(request, slug)
    )


@router.post("/worlds/{slug}")
async def world_save(
    request: Request,
    slug: str,
    worldname: str = Form(""),
    author: str = Form(""),
    publishdate: str = Form(""),
    archivedate: str = Form(""),
    filesize: str = Form(""),
    tags: str = Form(""),
    body: str = Form(""),
):
    md_path = paths.world_md_for(slug)
    w = world_mod.load(md_path)
    if w.doc.malformed:
        raise HTTPException(400, "front matter is not valid YAML; fix it by hand first")

    for label, value in (("publishdate", publishdate), ("archivedate", archivedate)):
        value = value.strip()
        if value and not paths.DATE_RE.match(value):
            ctx = _detail_ctx(request, slug, error=f"{label} must be YYYY-MM-DD or empty")
            return templates.TemplateResponse(request, "world_detail.html", ctx, status_code=400)

    updates = {
        "worldname": worldname.strip(),
        "author": author.strip(),
        "publishdate": publishdate.strip(),
        "archivedate": archivedate.strip(),
        "filesize": filesize.strip(),
        "tags": _split_tags(tags),
    }
    world_mod.save(w, updates, body=body)

    index.scan(request.app.state.db)

    return templates.TemplateResponse(
        request, "world_detail.html", _detail_ctx(request, slug, saved=True)
    )


@router.get("/worlds/{slug}/diff")
async def world_diff(request: Request, slug: str):
    md_path = paths.world_md_for(slug)
    rel = str(md_path.relative_to(paths.REPO_ROOT))
    return templates.TemplateResponse(
        request, "partials/diff.html", {"diff": git.file_diff(rel), "path": rel}
    )
