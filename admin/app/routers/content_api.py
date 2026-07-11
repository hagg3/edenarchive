from __future__ import annotations

import markdown as markdown_mod
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...core import content as content_mod
from ...core import git, paths
from ..templating import templates

router = APIRouter()


def _load_or_404(kind: str, filename: str) -> content_mod.ContentItem:
    try:
        return content_mod.load(kind, filename)
    except content_mod.ContentError:
        raise HTTPException(404) from None


@router.get("/content")
async def content_list(request: Request):
    return templates.TemplateResponse(
        request, "content.html",
        {
            "posts": content_mod.load_all("post"),
            "articles": content_mod.load_all("article"),
            "nav": "content",
        },
    )


@router.get("/content/{kind}/create")
async def content_create_form(request: Request, kind: str):
    if kind not in content_mod.DIR_FOR:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request, "content_edit.html", {"kind": kind, "item": None, "nav": "content"}
    )


@router.post("/content/{kind}/create")
async def content_create(
    request: Request, kind: str,
    title: str = Form(...), author: str = Form(""), date: str = Form(""), body: str = Form(""),
):
    if kind not in content_mod.DIR_FOR:
        raise HTTPException(404)
    try:
        item = content_mod.create(kind, title=title.strip(), author=author.strip(), date=date.strip(), body=body)
    except content_mod.ContentError as exc:
        ctx = {
            "kind": kind, "item": None, "error": str(exc), "nav": "content",
            "form": {"title": title, "author": author, "date": date, "body": body},
        }
        return templates.TemplateResponse(request, "content_edit.html", ctx, status_code=400)
    return RedirectResponse(f"/content/{kind}/{item.filename}", status_code=303)


def _detail_ctx(kind: str, filename: str, *, saved: bool = False, error: str = "") -> dict:
    item = _load_or_404(kind, filename)
    suggested = None
    if not item.doc.malformed:
        try:
            candidate = content_mod.filename_for(kind, date=item.date, title=item.title)
        except content_mod.ContentError:
            candidate = None
        if candidate and candidate != item.filename:
            suggested = candidate
    return {
        "kind": kind, "item": item, "saved": saved, "error": error,
        "suggested_filename": suggested, "nav": "content",
    }


@router.get("/content/{kind}/{filename}")
async def content_detail(request: Request, kind: str, filename: str):
    return templates.TemplateResponse(request, "content_edit.html", _detail_ctx(kind, filename))


@router.post("/content/{kind}/{filename}")
async def content_save(
    request: Request, kind: str, filename: str,
    title: str = Form(...), author: str = Form(""), date: str = Form(""), body: str = Form(""),
):
    item = _load_or_404(kind, filename)
    if item.doc.malformed:
        raise HTTPException(400, "front matter is not valid YAML; fix it by hand first")

    date = date.strip()
    if date and not paths.DATE_RE.match(date):
        ctx = _detail_ctx(kind, filename, error="date must be YYYY-MM-DD or empty")
        return templates.TemplateResponse(request, "content_edit.html", ctx, status_code=400)

    updates = {"title": title.strip(), "author": author.strip()}
    if kind == "post" or date:
        updates["date"] = date
    content_mod.save(item, updates, body=body)

    return templates.TemplateResponse(
        request, "content_edit.html", _detail_ctx(kind, filename, saved=True)
    )


@router.post("/content/{kind}/{filename}/rename")
async def content_rename(request: Request, kind: str, filename: str):
    item = _load_or_404(kind, filename)
    try:
        candidate = content_mod.filename_for(kind, date=item.date, title=item.title)
        renamed = content_mod.rename(item, candidate)
    except content_mod.ContentError as exc:
        ctx = _detail_ctx(kind, filename, error=str(exc))
        return templates.TemplateResponse(request, "content_edit.html", ctx, status_code=400)
    return RedirectResponse(f"/content/{kind}/{renamed.filename}", status_code=303)


@router.post("/content/{kind}/{filename}/delete")
async def content_delete(request: Request, kind: str, filename: str):
    item = _load_or_404(kind, filename)
    content_mod.delete(item)
    return RedirectResponse("/content", status_code=303)


@router.get("/content/{kind}/{filename}/diff")
async def content_diff(request: Request, kind: str, filename: str):
    item = _load_or_404(kind, filename)
    rel = str(item.path.relative_to(paths.REPO_ROOT))
    return templates.TemplateResponse(
        request, "partials/diff.html", {"diff": git.file_diff(rel), "path": rel}
    )


@router.post("/content/preview")
async def content_preview(body: str = Form("")):
    html = markdown_mod.markdown(body, extensions=["fenced_code", "tables"])
    return HTMLResponse(f'<div class="md-preview">{html}</div>')
