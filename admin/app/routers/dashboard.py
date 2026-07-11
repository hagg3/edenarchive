from __future__ import annotations

from fastapi import APIRouter, Request

from ...core import git, index
from ..templating import templates

router = APIRouter()


@router.get("/")
async def home(request: Request):
    conn = request.app.state.db
    counts = index.counts(conn)
    issues = index.issue_tallies(conn)
    changes = git.status()
    ab = git.ahead_behind()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "counts": counts,
            "issues": issues,
            "tags": index.all_tags(conn)[:20],
            "changes": changes,
            "branch": git.current_branch(),
            "ahead_behind": ab,
            "nav": "dashboard",
        },
    )


@router.post("/reindex")
async def reindex(request: Request):
    conn = request.app.state.db
    stats = index.scan(conn, force=True)
    counts = index.counts(conn)
    return templates.TemplateResponse(
        request,
        "partials/stats.html",
        {"counts": counts, "issues": index.issue_tallies(conn), "scan": stats},
    )
