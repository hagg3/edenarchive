"""Extract a .eden file from a world's zip and render its top-down map.

The extraction ladder is lifted verbatim from generate_missing_maps.py, which
already handles the packagings found in the archive:
  1. zip -> raw .eden
  2. zip -> gzip-compressed .eden, named *.eden.zip (gzip magic, not a real zip)
  3. zip -> zip -> .eden (double-nested)
  4. a bare gzip stream, with no outer zip at all, saved directly under
     `{id}.eden.zip` — confirmed live against the real archive (world
     `1584568651`): the outer real-zip wrap case 2 normally gets is just
     missing for this one. `extract_eden` used to `return None` for it
     (`zipfile.is_zipfile()` is False for raw gzip), so it silently failed to
     render — a currently-live bug, not a hypothetical one. World.ts already
     detects gzip by magic bytes regardless of filename/extension, so the fix
     needs no Python-side decompression: just get the bytes to `dest` under a
     `.eden` name and let node-mapgen do what it already does for case 2.

There is no genuine double-compression (gzip-of-gzip or zip-of-zip) anywhere
in the current archive — verified by walking every stored zip's payload
layers by magic bytes. What gets reported as "doubly zipped" is almost
certainly case 4 above: a `.eden.zip` that looks like it should unzip but
isn't a zip at all, just gzip wearing a `.zip` name.

Two safety mechanisms not in the original script:
- a pre-flight size check so worlds over the ~2 GB Node ArrayBuffer limit never
  spawn node in the first place (only exact for the "raw .eden" case; gzip and
  nested zips fall back to post-hoc classification, same as the plan calls for
  until the streaming payload hasher from M4 exists)
- a lockfile so the app's job queue and a concurrently-running
  generate_missing_maps.py never touch .mapgen-tmp/ at the same time
"""
from __future__ import annotations

import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import paths

GZIP_MAGIC = b"\x1f\x8b"

TOO_LARGE_BYTES = int(1.9 * 1024**3)

LOCK_FILE = paths.TEMP_DIR / ".lock"
_STALE_LOCK_SECONDS = 3600  # a lock this old is almost certainly a crashed process


class MapgenLockedError(RuntimeError):
    """Another mapgen process (this app or generate_missing_maps.py) is running."""


class MapgenError(RuntimeError):
    def __init__(self, message: str, error_class: str = "mapgen_error"):
        super().__init__(message)
        self.error_class = error_class


# --- lock ------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_lock() -> None:
    paths.TEMP_DIR.mkdir(exist_ok=True)
    if LOCK_FILE.exists():
        try:
            pid_s, _, ts_s = LOCK_FILE.read_text().strip().partition(" ")
            pid, ts = int(pid_s), float(ts_s)
        except (ValueError, OSError):
            pid, ts = -1, 0.0
        stale = (time.time() - ts) > _STALE_LOCK_SECONDS
        if pid != os.getpid() and _pid_alive(pid) and not stale:
            raise MapgenLockedError(
                f"map generation is already running (pid {pid}) — "
                "wait for it to finish, or check for a generate_missing_maps.py "
                "running in a terminal"
            )
    LOCK_FILE.write_text(f"{os.getpid()} {time.time()}")


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


# --- temp dir ----------------------------------------------------------------

def clear_temp_dir() -> None:
    if not paths.TEMP_DIR.exists():
        return
    for f in paths.TEMP_DIR.iterdir():
        if f == LOCK_FILE:
            continue
        try:
            if f.is_dir():
                for child in f.rglob("*"):
                    if child.is_file():
                        child.unlink()
                for child in sorted(f.rglob("*"), reverse=True):
                    if child.is_dir():
                        child.rmdir()
                f.rmdir()
            else:
                f.unlink()
        except OSError:
            pass


# --- extraction ladder (verbatim logic from generate_missing_maps.py) ------

def _is_junk(filename: str) -> bool:
    name = Path(filename).name
    return filename.startswith("__MACOSX") or name.startswith("._")


def _real_entries(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [e for e in z.infolist() if not _is_junk(e.filename)]


def _eden_name_for(source_name: str) -> str:
    """`whatever.eden.zip` / `whatever.zip` -> `whatever.eden`, without
    double-appending `.eden` if it's already there."""
    name = source_name
    if name.lower().endswith(".zip"):
        name = name[:-4]
    if not name.lower().endswith(".eden"):
        name += ".eden"
    return name


def _bare_gzip_fallback(path: Path, dest: Path) -> Path | None:
    """`path` isn't a zip at all — case 4 in the module docstring: a raw gzip
    stream saved directly as `{id}.eden.zip`, missing the outer real-zip wrap
    case 2 normally has. No decompression needed here: World.ts detects gzip
    by magic bytes regardless of filename, so just get the bytes to `dest`
    under a `.eden` name."""
    try:
        with path.open("rb") as f:
            magic = f.read(2)
    except OSError:
        return None
    if magic != GZIP_MAGIC:
        return None
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / _eden_name_for(path.name)
    shutil.copy2(path, out)
    return out


def extract_eden(zip_path: Path, dest: Path) -> Path | None:
    """Extract a world's .eden file from `zip_path` into `dest`."""
    if not zipfile.is_zipfile(zip_path):
        return _bare_gzip_fallback(zip_path, dest)

    with zipfile.ZipFile(zip_path, "r") as z:
        entries = _real_entries(z)
        if not entries:
            return None

        eden_entry = next((e for e in entries if e.filename.lower().endswith(".eden")), None)
        if eden_entry:
            z.extract(eden_entry, dest)
            result = next(dest.rglob(Path(eden_entry.filename).name), None)
            return result or next(dest.rglob("*.eden"), None)

        eden_zip_entry = next(
            (e for e in entries if e.filename.lower().endswith(".eden.zip")), None
        )
        if eden_zip_entry:
            extracted = dest / Path(eden_zip_entry.filename).name
            z.extract(eden_zip_entry, dest)
            if not extracted.exists():
                extracted = next(dest.rglob("*.eden.zip"), None)
            if not extracted:
                return None
            if zipfile.is_zipfile(extracted):
                return extract_eden(extracted, dest)
            renamed = extracted.with_name(_eden_name_for(extracted.name))
            extracted.rename(renamed)
            return renamed

        if len(entries) == 1:
            z.extract(entries[0], dest)
            extracted = next(dest.rglob(Path(entries[0].filename).name), None)
            if not extracted:
                return None
            if zipfile.is_zipfile(extracted):
                return extract_eden(extracted, dest)
            renamed = extracted.with_name(_eden_name_for(extracted.name))
            if renamed != extracted:
                extracted.rename(renamed)
            return renamed

    return None


def find_zip(world_id: str) -> Path | None:
    standard = paths.ASSETS_DIR / world_id / f"{world_id}.eden.zip"
    if standard.exists():
        return standard
    asset_dir = paths.ASSETS_DIR / world_id
    if asset_dir.is_dir():
        candidates = sorted(asset_dir.glob("*.zip")) + sorted(asset_dir.glob("*.eden.zip"))
        if candidates:
            return candidates[0]
    return None


# --- pre-flight size check ---------------------------------------------------

@dataclass
class Preflight:
    verdict: str  # "ok" | "too_large" | "unknown"
    bytes_: int | None = None


def preflight(zip_path: Path) -> Preflight:
    """Free (no decompression) size check. Only exact for the common "raw
    .eden inside the zip" packaging, where the zip's own central directory
    records the true uncompressed size. gzip-packaged and nested-zip worlds
    return "unknown" — their real size isn't knowable without the streaming
    payload hasher (M4); those fall back to post-hoc classification instead.
    """
    if not zipfile.is_zipfile(zip_path):
        return Preflight("unknown")
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            entries = _real_entries(z)
    except OSError:
        return Preflight("unknown")

    eden_entry = next((e for e in entries if e.filename.lower().endswith(".eden")), None)
    if eden_entry is None:
        return Preflight("unknown")

    size = eden_entry.file_size
    return Preflight("too_large" if size > TOO_LARGE_BYTES else "ok", size)


# --- post-hoc error classification ------------------------------------------

_TOO_LARGE_MARKERS = (
    "RangeError: Invalid typed array length",
    "Array buffer allocation failed",
    "Cannot create a string longer than",
    "JavaScript heap out of memory",
)


def classify_error(stderr: str, returncode: int) -> str:
    if any(marker in stderr for marker in _TOO_LARGE_MARKERS):
        return "too_large"
    if returncode != 0:
        return "node_error"
    return "unknown_error"
