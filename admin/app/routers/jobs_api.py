from __future__ import annotations

import asyncio
import html

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse

from ...core import index
from ..templating import templates

router = APIRouter(prefix="/jobs")


@router.get("")
async def job_list(request: Request):
    conn = request.app.state.db
    jobs = index.list_jobs(conn)
    return templates.TemplateResponse(
        request, "jobs.html", {"jobs": jobs, "nav": "jobs"}
    )


@router.get("/{job_id}")
async def job_detail(request: Request, job_id: int):
    conn = request.app.state.db
    job = index.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404)
    logs = index.job_logs(conn, job_id)
    return templates.TemplateResponse(
        request, "job_detail.html", {"job": job, "logs": logs, "nav": "jobs"}
    )


@router.post("/{job_id}/cancel")
async def job_cancel(request: Request, job_id: int):
    request.app.state.jobs.cancel(job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.get("/{job_id}/stream")
async def job_stream(request: Request, job_id: int):
    conn = request.app.state.db
    job = index.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404)

    queue = request.app.state.jobs
    live = queue.subscribe(job_id) if job["status"] in ("queued", "running") else None

    def _log_html(stream: str, line: str) -> str:
        return f'<div class="logline {stream}">{html.escape(line)}</div>'

    def _status_html(status: str) -> str:
        cls = "ok" if status == "ok" else "bad" if status in ("failed", "cancelled") else "warn"
        return f'<span class="pill {cls}">{html.escape(status)}</span>'

    async def gen():
        last_seq = -1
        for row in index.job_logs(conn, job_id):
            last_seq = row["seq"]
            yield f"event: log\ndata: {_log_html(row['stream'], row['line'])}\n\n"

        job_now = index.get_job(conn, job_id)
        if job_now["status"] not in ("queued", "running"):
            yield f"event: done\ndata: {_status_html(job_now['status'])}\n\n"
            return

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(live.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event.get("done"):
                    yield f"event: done\ndata: {_status_html(event['status'])}\n\n"
                    break
                if event["seq"] <= last_seq:
                    continue
                last_seq = event["seq"]
                yield f"event: log\ndata: {_log_html(event['stream'], event['line'])}\n\n"
        finally:
            if live is not None:
                queue.unsubscribe(job_id, live)

    return StreamingResponse(gen(), media_type="text/event-stream")
