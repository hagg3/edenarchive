from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from ...core import importer
from ...core import index
from ..templating import templates

router = APIRouter(prefix="/upload")

MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB — matches node-mapgen's own ceiling


@router.get("")
async def upload_form(request: Request):
    return templates.TemplateResponse(request, "upload.html", {"nav": "upload"})


@router.post("/stage")
async def upload_stage(request: Request, file: UploadFile):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"file is over the {MAX_UPLOAD_BYTES // 1024**3} GiB limit")
    if not data:
        raise HTTPException(400, "empty file")

    token = importer.receive_upload(data, file.filename or "upload.eden.zip")
    staged = importer.stage(token, file.filename or "upload.eden.zip")
    warnings = importer.check_against_archive(staged, request.app.state.db)

    return templates.TemplateResponse(
        request, "upload_review.html",
        {"staged": staged, "warnings": warnings, "nav": "upload"},
    )


@router.post("/commit")
async def upload_commit(
    request: Request,
    token: str = Form(...), original_filename: str = Form(...),
    worldname: str = Form(...), author: str = Form(""), archivedate: str = Form(""),
    tags: str = Form(""), confirm: bool = Form(False),
):
    conn = request.app.state.db
    staged = importer.stage(token, original_filename)
    warnings = importer.check_against_archive(staged, conn)

    blocking = [w for w in warnings if w.blocking]
    if blocking:
        return templates.TemplateResponse(
            request, "upload_review.html",
            {
                "staged": staged, "warnings": warnings, "nav": "upload",
                "error": "Can't import — this world is already archived (see the block below).",
                "form": {"worldname": worldname, "author": author, "archivedate": archivedate, "tags": tags},
            },
            status_code=400,
        )
    if warnings and not confirm:
        return templates.TemplateResponse(
            request, "upload_review.html",
            {
                "staged": staged, "warnings": warnings, "nav": "upload",
                "error": "This upload has similarity warnings — check \"import anyway\" to proceed.",
                "form": {"worldname": worldname, "author": author, "archivedate": archivedate, "tags": tags},
            },
            status_code=400,
        )

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        slug = importer.commit(
            staged, worldname=worldname, author=author, archivedate=archivedate, tags=tag_list
        )
    except importer.ImporterError as exc:
        return templates.TemplateResponse(
            request, "upload_review.html",
            {
                "staged": staged, "warnings": warnings, "nav": "upload", "error": str(exc),
                "form": {"worldname": worldname, "author": author, "archivedate": archivedate, "tags": tags},
            },
            status_code=400,
        )

    index.scan(conn)
    if staged.world_id:
        row = index.get_by_world_id(conn, staged.world_id)
        if row and not row["has_map"]:
            request.app.state.jobs.enqueue("mapgen", staged.world_id)

    return RedirectResponse(f"/worlds/{slug}", status_code=303)


@router.post("/discard")
async def upload_discard(token: str = Form(...)):
    importer.discard(token)
    return RedirectResponse("/upload", status_code=303)
