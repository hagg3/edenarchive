"""core/hashing.py: streaming zip + payload identity hashing.

The payload hash must be identity-stable across packaging: the same raw
.eden bytes stored as (a) a raw entry, (b) a gzip-compressed entry, or (c) a
gzip-compressed entry nested inside a real zip, must all produce the same
sha256 — that's what makes it useful for duplicate detection independent of
how a given world happened to get archived.
"""
from __future__ import annotations

import gzip
import hashlib
import zipfile

from admin.core import hashing


def _zip_with(path, arcname: str, data: bytes):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(arcname, data)


PAYLOAD = b"a fake eden world payload, repeated " * 1000


def test_hash_zip_bytes_is_sha256_of_the_file(tmp_path):
    p = tmp_path / "w.zip"
    p.write_bytes(b"not really a zip, just some bytes")
    assert hashing.hash_zip_bytes(p) == hashlib.sha256(p.read_bytes()).hexdigest()


def test_hash_payload_raw_entry(tmp_path):
    zp = tmp_path / "w.eden.zip"
    _zip_with(zp, "1234567890.eden", PAYLOAD)
    result = hashing.hash_payload(zp)
    assert result.error is None
    assert result.bytes_ == len(PAYLOAD)
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


def test_hash_payload_gzip_packaged_entry_matches_raw(tmp_path):
    zp = tmp_path / "w.eden.zip"
    _zip_with(zp, "1234567890.eden.zip", gzip.compress(PAYLOAD))
    result = hashing.hash_payload(zp)
    assert result.error is None
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


def test_hash_payload_nested_zip_matches_raw(tmp_path):
    inner = tmp_path / "inner.eden.zip"
    _zip_with(inner, "1234567890.eden", PAYLOAD)
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.write(inner, "bundle/1234567890.eden.zip")
    result = hashing.hash_payload(outer)
    assert result.error is None
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


def test_hash_payload_bare_gzip_no_outer_zip_matches_raw(tmp_path):
    """The packaging variant found live on world 1584568651: no outer zip at
    all, just a gzip stream saved directly as `{id}.eden.zip`."""
    bare = tmp_path / "1584568651.eden.zip"
    bare.write_bytes(gzip.compress(PAYLOAD))
    result = hashing.hash_payload(bare)
    assert result.error is None
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


def test_hash_payload_ignores_macosx_junk(tmp_path):
    zp = tmp_path / "w.eden.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("__MACOSX/._1234567890.eden", b"junk")
        z.writestr("1234567890.eden", PAYLOAD)
    result = hashing.hash_payload(zp)
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


def test_hash_payload_not_a_zip_not_gzip_returns_error(tmp_path):
    fake = tmp_path / "w.eden.zip"
    fake.write_bytes(b"neither zip nor gzip magic here")
    result = hashing.hash_payload(fake)
    assert result.sha256 is None
    assert result.error is not None


def test_hash_payload_empty_zip_returns_error(tmp_path):
    zp = tmp_path / "w.eden.zip"
    with zipfile.ZipFile(zp, "w"):
        pass
    result = hashing.hash_payload(zp)
    assert result.sha256 is None
    assert result.error is not None


def test_hash_payload_streams_large_payload_without_loading_fully(tmp_path):
    """Not a memory-usage assertion (hard to check portably) — just confirms
    correctness holds for a payload much bigger than the 1 MiB chunk size,
    exercising the multi-chunk read loop."""
    big = b"x" * (1 << 22)  # 4 MiB, several chunks at CHUNK=1 MiB
    zp = tmp_path / "w.eden.zip"
    _zip_with(zp, "1234567890.eden", big)
    result = hashing.hash_payload(zp)
    assert result.bytes_ == len(big)
    assert result.sha256 == hashlib.sha256(big).hexdigest()
