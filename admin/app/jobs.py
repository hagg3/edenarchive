"""Single in-process asyncio job queue, concurrency 1.

No Celery, no Redis — this is a single-user local app. Concurrency 1 is a hard
invariant: it's what keeps ".mapgen-tmp/ never holds more than one unzipped
world" true. Log lines are written to the `job_logs` table and also pushed to
any live SSE subscriber for that job.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

from ..core import edenserver, hashing, index, mapgen
from ..core import paths
from ..core import world as world_mod

MAPGEN_TIMEOUT = 300
SERVER_FETCH_TIMEOUT = 300
PREVIEW_BACKFILL_SLEEP = 0.5


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
            elif job["kind"] == "payload_hash":
                await self._run_payload_hash(job_id, job["target"])
            elif job["kind"] == "server_fetch":
                await self._run_server_fetch(job_id, job["target"], job["params"])
            elif job["kind"] == "preview_backfill":
                await self._run_preview_backfill(job_id, job["target"])
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
                if slug:
                    self._fold_technical_meta(job_id, slug, world_id)
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

    def _fold_technical_meta(self, job_id: int, slug: str, world_id: str) -> None:
        """After a successful mapgen run, read the meta.json sidecar node-mapgen
        wrote next to map.png and fold it into the world's front matter (format,
        chunk dimensions, sky color, seed, spawn). Best-effort: a failure here
        must not turn a successful map render into a failed job."""
        meta = mapgen.read_meta_sidecar(world_id)
        if not meta:
            return
        updates = mapgen.frontmatter_updates_from_meta(meta)
        if not updates:
            return
        try:
            w = world_mod.load(paths.WORLDS_DIR / f"{slug}.md")
            world_mod.save(w, updates)
            self._log(job_id, "stdout", f"technical info updated: {', '.join(updates)}")
        except Exception as exc:  # noqa: BLE001 — best-effort, must not fail the job
            self._log(job_id, "stderr", f"failed to write technical info: {exc}")

    async def _run_payload_hash(self, job_id: int, slug: str) -> None:
        """Streams the decompressed .eden payload through sha256 — pure
        Python I/O, no subprocess, no lock (doesn't touch .mapgen-tmp/), so
        it can safely run alongside a mapgen job. Handles worlds too large
        for node-mapgen too (that's the point — see core/hashing.py)."""
        row = index.get(self.conn, slug)
        if row is None or not row["has_zip"]:
            self._log(job_id, "stderr", "no zip on disk for this world")
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="no_zip", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})
            return

        zip_path = Path(row["zip_path"])
        self._log(job_id, "stdout", f"hashing {zip_path.name}")
        result = await asyncio.to_thread(hashing.hash_payload, zip_path)
        index.update_payload_hash(self.conn, slug, result.sha256, result.bytes_, result.error)

        if result.error:
            self._log(job_id, "stderr", result.error)
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="hash_error", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})
            return

        self._log(job_id, "stdout", f"sha256={result.sha256} bytes={result.bytes_}")
        index.update_job(
            self.conn, job_id, status="ok", ended_at=index.now(),
            result=result.sha256,
        )
        self._publish(job_id, {"done": True, "status": "ok"})

    async def _run_server_fetch(self, job_id: int, world_id: str, params_json: str | None) -> None:
        """Downloads a world from the Eden game servers into a fresh staged
        upload, so the existing /upload/review -> /upload/commit flow can
        take it from there unchanged."""
        params = json.loads(params_json or "{}")
        server_name = params.get("server", "current")
        display_name = params.get("name") or world_id

        try:
            server = edenserver.get_server(server_name)
        except edenserver.EdenServerError as exc:
            self._log(job_id, "stderr", str(exc))
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="server_error", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})
            return

        paths.ensure_runtime_dirs()
        import uuid

        token = uuid.uuid4().hex[:12]
        dest = paths.UPLOAD_DIR / f"{token}.eden"

        loop = asyncio.get_running_loop()
        last_logged = 0

        def progress(downloaded: int, total: int | None) -> None:
            nonlocal last_logged
            if downloaded - last_logged < 1_000_000 and (total is None or downloaded < total):
                return
            last_logged = downloaded
            line = f"{downloaded} bytes" if total is None else f"{downloaded}/{total} bytes"
            loop.call_soon_threadsafe(self._log, job_id, "stdout", line)

        self._log(job_id, "stdout", f"downloading {display_name!r} ({world_id}) from {server_name}")
        try:
            await asyncio.wait_for(
                asyncio.to_thread(edenserver.download, world_id, server, dest, progress=progress),
                timeout=SERVER_FETCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            dest.unlink(missing_ok=True)
            self._log(job_id, "stderr", f"timed out after {SERVER_FETCH_TIMEOUT}s")
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="server_error", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})
            return
        except edenserver.DownloadTooLarge as exc:
            self._log(job_id, "stderr", str(exc))
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="too_large", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})
            return
        except Exception as exc:  # noqa: BLE001 — network/IO failure, not a bug
            self._log(job_id, "stderr", f"download failed: {exc}")
            index.update_job(
                self.conn, job_id, status="failed",
                error_class="server_error", ended_at=index.now(),
            )
            self._publish(job_id, {"done": True, "status": "failed"})
            return

        filename = f"{display_name} {world_id}.eden"
        self._log(job_id, "stdout", f"done — review at /upload/review/{token}")
        index.update_job(
            self.conn, job_id, status="ok", ended_at=index.now(),
            result=json.dumps({"token": token, "filename": filename}),
        )
        self._publish(job_id, {"done": True, "status": "ok"})

    async def _run_preview_backfill(self, job_id: int, target: str) -> None:
        """Best-effort bulk fetch of `{id}.eden.png` previews for worlds that
        don't have one. Misses are expected and normal — a server-side glitch
        left many worlds with no preview at all — so they're logged as skips,
        not errors, and the job still finishes 'ok'."""
        if target and target != "all":
            row = index.get_by_world_id(self.conn, target)
            rows = [row] if row is not None else []
        else:
            rows = list(self.conn.execute(
                "SELECT slug, world_id FROM worlds WHERE has_preview=0 AND world_id IS NOT NULL"
            ))

        written = already_had = not_on_server = errors = 0
        self._log(job_id, "stdout", f"checking {len(rows)} world(s)")

        for row in rows:
            world_id, slug = row["world_id"], row["slug"]
            dest_dir = paths.asset_dir_for(world_id)
            dest = dest_dir / f"{world_id}.eden.png"
            if dest.exists():
                already_had += 1
                continue

            data, server = await asyncio.to_thread(edenserver.fetch_preview_any, world_id)
            if data is None:
                not_on_server += 1
                self._log(job_id, "stdout", f"{world_id}: skipped: no preview on server")
                await asyncio.sleep(PREVIEW_BACKFILL_SLEEP)
                continue

            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                paths.assert_writable(dest).write_bytes(data)
            except OSError as exc:
                errors += 1
                self._log(job_id, "stderr", f"{world_id}: {exc}")
                await asyncio.sleep(PREVIEW_BACKFILL_SLEEP)
                continue

            index.refresh_assets(self.conn, slug)
            written += 1
            self._log(job_id, "stdout", f"{world_id}: written (from {server})")
            await asyncio.sleep(PREVIEW_BACKFILL_SLEEP)

        summary = (
            f"written={written} already_had={already_had} "
            f"not_on_server={not_on_server} errors={errors}"
        )
        self._log(job_id, "stdout", summary)
        index.update_job(self.conn, job_id, status="ok", ended_at=index.now(), result=summary)
        self._publish(job_id, {"done": True, "status": "ok"})
