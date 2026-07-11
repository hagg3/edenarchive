"""Eden Archive Admin — local-only FastAPI app.

Binds to loopback only. It writes plain files into the working tree; the
archivist reviews with `git diff` and pushes. It never talks to GitHub.
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..core import git, index, paths
from .jobs import JobQueue
from .routers import assets_api, dashboard, git_api, jobs_api, tags_api, worlds
from .templating import templates

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    paths.ensure_runtime_dirs()
    conn = index.connect()
    stats = index.scan(conn)
    STATE["conn"] = conn
    STATE["scan"] = stats
    # If the tree was already dirty at startup, later diffs aren't all ours.
    STATE["dirty_at_start"] = git.is_dirty()
    app.state.db = conn

    jobs = JobQueue(conn)
    jobs.start()
    app.state.jobs = jobs

    print(
        f"[admin] indexed {stats['scanned']} worlds "
        f"({stats['updated']} updated, {stats['skipped']} unchanged)"
    )
    print("[admin] http://127.0.0.1:8765")
    try:
        yield
    finally:
        await jobs.stop()
        conn.close()


app = FastAPI(title="Eden Archive Admin", lifespan=lifespan)

# Routers first: several explicit routes live under /assets (the asset grid,
# map/preview job endpoints) and must be matched before the catch-all static
# mount below, which otherwise swallows the whole /assets/* path space.
app.include_router(dashboard.router)
app.include_router(worlds.router)
app.include_router(git_api.router)
app.include_router(assets_api.router)
app.include_router(jobs_api.router)
app.include_router(tags_api.router)

app.mount(
    "/static", StaticFiles(directory=paths.REPO_ROOT / "admin/app/static"), name="static"
)
# Serve the repo's own asset files (map.png, previews) so thumbnails render.
# Anything not matched by the routers above (i.e. *.png, *.zip paths) falls
# through to here.
app.mount(
    "/assets", StaticFiles(directory=paths.ASSETS_DIR), name="assets"
)


def db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(
        request, "error.html", {"code": 404, "message": "Not found"}, status_code=404
    )


@app.exception_handler(ValueError)
async def bad_value(request: Request, exc: ValueError):
    return HTMLResponse(f"<div class='err'>{exc}</div>", status_code=400)
