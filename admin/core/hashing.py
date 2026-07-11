"""Streaming payload identity hashing.

Reuses mapgen.py's packaging knowledge (raw / gzip / nested-zip / bare-gzip,
see mapgen.py's module docstring) but never writes to disk or holds a full
payload in memory — hashes are computed by streaming through zip/gzip layers
in fixed-size chunks. This is what lets even the worlds too large for
node-mapgen (Starling City: 8.8 GB) get a payload identity hash: peak memory
is ~1 MiB regardless of file size.

Two tiers, per ADMIN_APP_PLAN.md:
- Tier 1, zip bytes (`hash_zip_bytes`): cheap, computed during every scan.
  Catches byte-identical re-uploads but nothing else — the same world
  packaged two different ways gives different zip hashes.
- Tier 2, decompressed payload (`hash_payload`): the canonical identity,
  computed by a background job. Two worlds with the same payload hash are
  the same world, regardless of packaging.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from . import mapgen

CHUNK = 1 << 20  # 1 MiB


@dataclass
class PayloadHash:
    sha256: str | None
    bytes_: int | None
    error: str | None


def hash_zip_bytes(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def _stream_hash(fileobj: BinaryIO) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    while block := fileobj.read(CHUNK):
        h.update(block)
        total += len(block)
    return h.hexdigest(), total


def _hash_entry(open_fn: Callable[[], BinaryIO]) -> tuple[str, int]:
    """`open_fn()` returns a fresh readable stream each call (zip entry
    streams aren't seekable, so gzip-detection and the real read need
    separate opens). Transparently unwraps one gzip layer if present."""
    with open_fn() as f:
        head = f.read(2)
    with open_fn() as f:
        if head == mapgen.GZIP_MAGIC:
            with gzip.GzipFile(fileobj=f) as gz:
                return _stream_hash(gz)
        return _stream_hash(f)


def _hash_from_zipfile(z: zipfile.ZipFile) -> PayloadHash:
    entries = mapgen._real_entries(z)
    if not entries:
        return PayloadHash(None, None, "zip has no real entries")

    eden_entry = next((e for e in entries if e.filename.lower().endswith(".eden")), None)
    if eden_entry:
        sha, size = _hash_entry(lambda: z.open(eden_entry))
        return PayloadHash(sha, size, None)

    eden_zip_entry = next(
        (e for e in entries if e.filename.lower().endswith(".eden.zip")), None
    )
    candidate = eden_zip_entry or (entries[0] if len(entries) == 1 else None)
    if candidate is None:
        return PayloadHash(None, None, "no .eden payload found")

    with z.open(candidate) as f:
        head4 = f.read(4)
    if head4 == b"PK\x03\x04":
        # Nested real zip (rare — CLAUDE.md's "outer zip contains the entire
        # .eden.zip bundle" case). Not currently observed anywhere in the
        # archive, but read defensively: this is a "wrapper" zip in practice
        # (small), so buffering it fully is an acceptable tradeoff to reuse
        # zipfile's central-directory parsing (which needs a seekable
        # source, unlike a streamed zip entry).
        with z.open(candidate) as f:
            nested = f.read()
        try:
            with zipfile.ZipFile(io.BytesIO(nested)) as nz:
                return _hash_from_zipfile(nz)
        except zipfile.BadZipFile:
            return PayloadHash(None, None, "nested entry looked like a zip but failed to open")

    sha, size = _hash_entry(lambda: z.open(candidate))
    return PayloadHash(sha, size, None)


def _hash_payload_inner(zip_path: Path) -> PayloadHash:
    if not zipfile.is_zipfile(zip_path):
        # Case 4 in mapgen.py: a bare gzip stream with no outer zip wrap.
        with zip_path.open("rb") as f:
            magic = f.read(2)
        if magic != mapgen.GZIP_MAGIC:
            return PayloadHash(None, None, "not a zip and not a gzip stream")
        sha, size = _hash_entry(lambda: zip_path.open("rb"))
        return PayloadHash(sha, size, None)

    with zipfile.ZipFile(zip_path, "r") as z:
        return _hash_from_zipfile(z)


def hash_payload(zip_path: Path) -> PayloadHash:
    """Stream-hash the decompressed .eden payload — the canonical identity,
    independent of which packaging variant it happens to be stored as. Never
    extracts to disk, never materializes the full (possibly multi-GB)
    payload in memory."""
    try:
        return _hash_payload_inner(zip_path)
    except Exception as exc:  # noqa: BLE001 — always return a PayloadHash, never raise
        return PayloadHash(None, None, f"{type(exc).__name__}: {exc}")
