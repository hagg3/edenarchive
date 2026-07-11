"""admin/app/jobs.py: JobQueue cancellation semantics.

Regression tests for a concurrency bug found via live testing (see
ADMIN_APP_PLAN.md, "M2 handoff"): the old `_run()` ran a job's body inline in
the worker-loop task, so `cancel(job_id)` and the worker loop itself were the
same asyncio task. That meant (a) `stop()` never actually completed — the
per-job `except CancelledError` swallowed the cancellation and the loop moved
on to the next queued job instead of exiting — and (b) the cancelled job's
subprocess was never killed, leaving an orphaned `node` process running
concurrently with the next job's.

These tests use a real `sleep 5` subprocess (swapped in for the `node`
invocation via a patched `asyncio.create_subprocess_exec`) so they exercise
the actual kill/wait code paths in milliseconds, without depending on
node-mapgen or a real world file. No pytest-asyncio dependency: each test
wraps its body in `asyncio.run`.
"""
from __future__ import annotations

import asyncio
import zipfile

import pytest

from admin.app import jobs as jobs_mod
from admin.core import index, mapgen

WORLD_ID = "1234567890"


def _wire_paths(tmp_path, monkeypatch):
    assets_dir = tmp_path / "assets"
    temp_dir = tmp_path / "mapgen-tmp"
    runtime_dir = tmp_path / ".runtime"

    for mod in (mapgen.paths, jobs_mod.paths, index.paths):
        monkeypatch.setattr(mod, "ASSETS_DIR", assets_dir, raising=False)
        monkeypatch.setattr(mod, "TEMP_DIR", temp_dir, raising=False)
        monkeypatch.setattr(mod, "RUNTIME_DIR", runtime_dir, raising=False)
        monkeypatch.setattr(mod, "BACKUP_DIR", runtime_dir / "backups", raising=False)
        monkeypatch.setattr(mod, "UPLOAD_DIR", runtime_dir / "uploads", raising=False)

    monkeypatch.setattr(mapgen, "LOCK_FILE", temp_dir / ".lock")
    monkeypatch.setattr(jobs_mod.paths, "MAPGEN_DIST", tmp_path / "generate-map.js")
    monkeypatch.setattr(jobs_mod.paths, "NODE_MAPGEN_DIR", tmp_path)

    asset_dir = assets_dir / WORLD_ID
    asset_dir.mkdir(parents=True)
    zpath = asset_dir / f"{WORLD_ID}.eden.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr(f"{WORLD_ID}.eden", b"tiny eden payload, well under the size cap")
    return zpath


def _patch_slow_subprocess(monkeypatch):
    """Make the mapgen job spawn `sleep 5` instead of a real node invocation,
    so tests can cancel it and assert the subprocess actually dies."""
    real_create_subprocess_exec = asyncio.create_subprocess_exec

    async def fake_create_subprocess_exec(*args, **kwargs):
        return await real_create_subprocess_exec(
            "sleep", "5",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )

    monkeypatch.setattr(jobs_mod.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(jobs_mod.shutil, "which", lambda name: "/usr/bin/env")


async def _wait_until(predicate, timeout=3.0, interval=0.02):
    elapsed = 0.0
    while not predicate():
        await asyncio.sleep(interval)
        elapsed += interval
        if elapsed > timeout:
            raise AssertionError("condition not met in time")


async def _no_leaked_sleep_processes():
    ps = await asyncio.create_subprocess_shell(
        "pgrep -f 'sleep 5' || true", stdout=asyncio.subprocess.PIPE
    )
    out, _ = await ps.communicate()
    assert out.decode().strip() == ""


def test_cancel_kills_subprocess_and_worker_continues(tmp_path, monkeypatch):
    _wire_paths(tmp_path, monkeypatch)
    _patch_slow_subprocess(monkeypatch)
    conn = index.connect(tmp_path / ".runtime" / "index.db")

    async def body():
        queue = jobs_mod.JobQueue(conn)
        queue.start()
        try:
            job1 = queue.enqueue("mapgen", WORLD_ID)
            job2 = queue.enqueue("mapgen", WORLD_ID)

            await _wait_until(lambda: index.get_job(conn, job1)["status"] == "running")
            await _wait_until(
                lambda: queue._current_task is not None and not queue._current_task.done()
            )

            assert queue.cancel(job1) is True

            await _wait_until(lambda: index.get_job(conn, job1)["status"] == "cancelled")
            # the worker must move on to the second job rather than hanging
            await _wait_until(
                lambda: index.get_job(conn, job2)["status"] in ("running", "ok", "failed")
            )
        finally:
            await queue.stop()

        await _no_leaked_sleep_processes()

    try:
        asyncio.run(body())
    finally:
        conn.close()


def test_stop_kills_subprocess_and_worker_task_exits_promptly(tmp_path, monkeypatch):
    _wire_paths(tmp_path, monkeypatch)
    _patch_slow_subprocess(monkeypatch)
    conn = index.connect(tmp_path / ".runtime" / "index.db")

    async def body():
        queue = jobs_mod.JobQueue(conn)
        queue.start()

        job1 = queue.enqueue("mapgen", WORLD_ID)
        await _wait_until(lambda: index.get_job(conn, job1)["status"] == "running")
        await _wait_until(
            lambda: queue._current_task is not None and not queue._current_task.done()
        )

        await asyncio.wait_for(queue.stop(), timeout=2.0)  # must not hang

        assert queue._worker_task.done()
        assert index.get_job(conn, job1)["status"] == "cancelled"

        await _no_leaked_sleep_processes()

    try:
        asyncio.run(body())
    finally:
        conn.close()


def test_start_sweeps_stale_running_jobs_from_a_prior_process(tmp_path, monkeypatch):
    _wire_paths(tmp_path, monkeypatch)
    conn = index.connect(tmp_path / ".runtime" / "index.db")

    async def body():
        index.create_job(conn, "mapgen", WORLD_ID)
        stuck = index.create_job(conn, "mapgen", WORLD_ID)
        index.update_job(conn, stuck, status="running", started_at=index.now())

        queue = jobs_mod.JobQueue(conn)
        queue.start()
        try:
            assert index.get_job(conn, stuck)["status"] == "cancelled"
        finally:
            await queue.stop()

    try:
        asyncio.run(body())
    finally:
        conn.close()


def _insert_world_row(conn, slug, zip_path):
    conn.execute(
        "INSERT INTO worlds (slug, md_path, world_id, has_zip, zip_path) "
        "VALUES (?,?,?,1,?)",
        (slug, f"_worlds/{slug}.md", WORLD_ID, str(zip_path)),
    )
    conn.commit()


def test_payload_hash_job_runs_and_updates_the_row(tmp_path, monkeypatch):
    zpath = _wire_paths(tmp_path, monkeypatch)
    conn = index.connect(tmp_path / ".runtime" / "index.db")
    _insert_world_row(conn, "some-world", zpath)

    async def body():
        queue = jobs_mod.JobQueue(conn)
        queue.start()
        try:
            job_id = queue.enqueue("payload_hash", "some-world")
            await _wait_until(lambda: index.get_job(conn, job_id)["status"] in ("ok", "failed"))
            job = index.get_job(conn, job_id)
            assert job["status"] == "ok"
            assert job["result"]  # the sha256

            row = index.get(conn, "some-world")
            assert row["payload_sha256"] == job["result"]
            assert row["payload_hashed_at"] is not None
        finally:
            await queue.stop()

    try:
        asyncio.run(body())
    finally:
        conn.close()


def test_payload_hash_job_records_error_without_crashing_the_worker(tmp_path, monkeypatch):
    _wire_paths(tmp_path, monkeypatch)
    conn = index.connect(tmp_path / ".runtime" / "index.db")
    bad_zip = tmp_path / "assets" / WORLD_ID / "broken.eden.zip"
    bad_zip.write_bytes(b"neither zip nor gzip")
    _insert_world_row(conn, "broken-world", bad_zip)

    async def body():
        queue = jobs_mod.JobQueue(conn)
        queue.start()
        try:
            job_id = queue.enqueue("payload_hash", "broken-world")
            await _wait_until(lambda: index.get_job(conn, job_id)["status"] in ("ok", "failed"))
            assert index.get_job(conn, job_id)["status"] == "failed"
            row = index.get(conn, "broken-world")
            assert row["payload_sha256"] is None
            assert row["payload_error"]
        finally:
            await queue.stop()

    try:
        asyncio.run(body())
    finally:
        conn.close()
