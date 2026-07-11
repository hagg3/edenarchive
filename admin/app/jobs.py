"""Single in-process asyncio job queue, concurrency 1.

No Celery, no Redis — this is a single-user local app. Concurrency 1 is a hard
invariant: it's what keeps ".mapgen-tmp/ never holds more than one unzipped
world" true. Log lines are written to the `job_logs` table and also pushed to
any live SSE subscriber for that job.
"""
from __future__ import annotations

import asyncio
import shutil
import sqlite3

from ..core import index, mapgen
from ..core import paths

MAPGEN_TIMEOUT = 300


class JobQueue:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._subscribers: dict[int, list[asyncio.Queue]] = {}
        self._worker_task: asyncio.Task | None = None
        self._current_task: asyncio.Task | None = None
        self._cancelled: set[int] = set()
        self._shutting_down = False

    def start(self) -> None:
        # A previous process may have been force-killed (pkill -9, crash) with
        # jobs still marked queued/running — those rows would otherwise sit
        # "in progress" forever in the /jobs UI.
        self.conn.execute(
            "UPDATE jobs SET status='cancelled', ended_at=? WHERE status IN ('queued','running')",
            (index.now(),),
        )
        self.conn.commit()
        self._worker_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker_task:
            self._shutting_down = True
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    # --- public API ----------------------------------------------------

    def enqueue(self, kind: str, target: str, params: dict | None = None) -> int:
        job_id = index.create_job(self.conn, kind, target, params)
        self._queue.put_nowait(job_id)
        return job_id

    def cancel(self, job_id: int) -> bool:
        job = index.get_job(self.conn, job_id)
        if job is None or job["status"] not in ("queued", "running"):
            return False
        self._cancelled.add(job_id)
        if job["status"] == "running" and self._current_task:
            self._current_task.cancel()
        return True

    def subscribe(self, job_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(job_id, []).append(q)
        return q

    def unsubscribe(self, job_id: int, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(job_id, [])
        if q in subs:
            subs.remove(q)

    def _publish(self, job_id: int, event: dict) -> None:
        for q in self._subscribers.get(job_id, []):
            q.put_nowait(event)

    def _log(self, job_id: int, stream: str, line: str) -> None:
        seq = index.append_log(self.conn, job_id, stream, line)
        self._publish(job_id, {"seq": seq, "stream": stream, "line": line})

    # --- worker ----------------------------------------------------------

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            if job_id in self._cancelled:
                index.update_job(self.conn, job_id, status="cancelled", ended_at=index.now())
                self._publish(job_id, {"done": True, "status": "cancelled"})
                self._cancelled.discard(job_id)
                self._queue.task_done()
                continue

            job = index.get_job(self.conn, job_id)
            if job is None:
                self._queue.task_done()
                continue

            # Run the job body as its own task, distinct from this worker-loop
            # task, so that cancel(job_id) can target *only* the job and never
            # the loop that keeps serving the queue.
            self._current_task = asyncio.create_task(self._run_job(job_id, job))
            try:
                await self._current_task
            except asyncio.CancelledError:
                # _run_job always re-raises CancelledError after cleaning up
                # (killing any subprocess, releasing the lock, recording the
                # job as cancelled). Only propagate further — and exit this
                # loop — if we're actually shutting down; a per-job cancel()
                # should just move on to the next queued job.
                if self._shutting_down:
                    raise
            finally:
                self._current_task = None
                self._cancelled.discard(job_id)
                self._queue.task_done()

    async def _run_job(self, job_id: int, job: sqlite3.Row) -> None:
        index.update_job(self.conn, job_id, status="running", started_at=index.now())
        try:
            if job["kind"] == "mapgen":
                await self._run_mapgen(job_id, job["target"])
            else:
                index.update_job(
                    self.conn, job_id, status="failed",
                    error_class="unknown_kind", ended_at=index.now(),
                )
        except asyncio.CancelledError:
            index.update_job(
                self.conn, job_id, status="cancelled", ended_at=index.now()
            )
            self._publish(job_id, {"done": True, "status": "cancelled"})
            raise
        except Exception as exc:  # noqa: BLE001 — job must never kill the worker
            self._log(job_id, "stderr", f"unhandled error: {exc}")
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="internal_error", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})

    async def _run_mapgen(self, job_id: int, world_id: str) -> None:
        row = index.get_by_world_id(self.conn, world_id)
        slug = row["slug"] if row else None

        zip_path = mapgen.find_zip(world_id)
        if zip_path is None:
            self._log(job_id, "stderr", "no zip found for this world")
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="no_zip", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})
            return

        pf = mapgen.preflight(zip_path)
        if pf.verdict == "too_large":
            self._log(
                job_id, "stdout",
                f"payload too large for node-mapgen ({pf.bytes_ / 1024**3:.1f} GB "
                "uncompressed) — skipped, use manual map.png upload",
            )
            index.update_job(
                self.conn, job_id, status="skipped",
                error_class="too_large", ended_at=index.now(),
            )
            if slug:
                index.refresh_assets(self.conn, slug, map_status="too_large")
            self._publish(job_id, {"done": True, "status": "skipped"})
            return

        try:
            mapgen.acquire_lock()
        except mapgen.MapgenLockedError as exc:
            self._log(job_id, "stderr", str(exc))
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="locked", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})
            return

        proc: asyncio.subprocess.Process | None = None
        try:
            mapgen.clear_temp_dir()
            paths.TEMP_DIR.mkdir(exist_ok=True)
            self._log(job_id, "stdout", f"extracting {zip_path.name}")
            eden_file = await asyncio.to_thread(mapgen.extract_eden, zip_path, paths.TEMP_DIR)
            if eden_file is None:
                self._log(job_id, "stderr", "no .eden payload found inside the zip")
                index.update_job(
                    self.conn, job_id, status="failed",
                    error_class="no_eden", ended_at=index.now(),
                )
                self._publish(job_id, {"done": True, "status": "failed"})
                return

            map_path = paths.ASSETS_DIR / world_id / "map.png"
            map_path.parent.mkdir(parents=True, exist_ok=True)

            node = shutil.which("node")
            if node is None:
                self._log(job_id, "stderr", "node not found on PATH")
                index.update_job(
                    self.conn, job_id, status="failed",
                    error_class="env_error", ended_at=index.now(),
                )
                self._publish(job_id, {"done": True, "status": "failed"})
                return

            args = [node, str(paths.MAPGEN_DIST), str(eden_file), str(map_path)]
            self._log(job_id, "stdout", f"running node-mapgen on {eden_file.name}")
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=paths.NODE_MAPGEN_DIR,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def _pump(stream, label):
                text = ""
                while True:
                    chunk = await stream.readline()
                    if not chunk:
                        break
                    line = chunk.decode(errors="replace").rstrip("\n")
                    self._log(job_id, label, line)
                    text += line + "\n"
                return text

            try:
                stdout_text, stderr_text = await asyncio.wait_for(
                    asyncio.gather(_pump(proc.stdout, "stdout"), _pump(proc.stderr, "stderr")),
                    timeout=MAPGEN_TIMEOUT,
                )
                returncode = await proc.wait()
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                self._log(job_id, "stderr", f"timed out after {MAPGEN_TIMEOUT}s")
                index.update_job(
                    self.conn, job_id, status="failed",
                    error_class="timeout", ended_at=index.now(),
                )
                self._publish(job_id, {"done": True, "status": "failed"})
                return

            if returncode == 0 and map_path.exists():
                self._log(job_id, "stdout", "done")
                index.update_job(
                    self.conn, job_id, status="ok", ended_at=index.now(),
                    result="map.png written",
                )
                if slug:
                    index.refresh_assets(self.conn, slug, map_status="ok")
                self._publish(job_id, {"done": True, "status": "ok"})
            else:
                error_class = mapgen.classify_error(stderr_text, returncode)
                index.update_job(
                    self.conn, job_id, status="failed",
                    error_class=error_class, ended_at=index.now(),
                )
                if slug and error_class == "too_large":
                    index.refresh_assets(self.conn, slug, map_status="too_large")
                self._publish(job_id, {"done": True, "status": "failed"})
        finally:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            mapgen.clear_temp_dir()
            mapgen.release_lock()
