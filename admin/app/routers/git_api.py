from __future__ import annotations

from fastapi import APIRouter, Request

from ...core import git
from ..templating import templates

router = APIRouter(prefix="/git")


def _panel(request: Request, message: str = ""):
    changes = git.status()
    return templates.TemplateResponse(
        request,
        "partials/git_panel.html",
        {
            "changes": changes,
            "grouped": git.grouped_status(),
            "branch": git.current_branch(),
            "ahead_behind": git.ahead_behind(),
            "commit_hint": git.commit_hint(changes),
            "message": message,
        },
    )


@router.get("")
async def panel(request: Request):
    return _panel(request)


@router.post("/fetch")
async def fetch(request: Request):
    """The only network git operation in the app, and only on an explicit click."""
    ok, msg = git.fetch()
    return _panel(request, message=msg if ok else f"fetch failed: {msg}")
