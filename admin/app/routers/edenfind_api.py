"""Links out to the EdenFind tool (admin-filelist/) from the admin UI.

EdenFind is a separate stdlib-only ThreadingHTTPServer (see
admin-filelist/edenfind/server.py) — it is not an ASGI app, so it can't be
mounted directly into this FastAPI app. Instead, main.py's lifespan spawns it
as a subprocess on its own loopback port, and this route just redirects to it
(the navbar link opens it in a new tab) rather than embedding it.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.get("/edenfind")
async def edenfind(request: Request):
    port = request.app.state.edenfind_port
    return RedirectResponse(f"http://127.0.0.1:{port}/")
