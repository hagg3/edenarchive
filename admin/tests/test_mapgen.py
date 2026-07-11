"""core/mapgen.py: extraction ladder, pre-flight size check, error
classification, and the lockfile that keeps the admin app's job queue and a
concurrently-running generate_missing_maps.py off .mapgen-tmp/ at the same
time. All against tmp_path fixtures — never touches the real archive."""
from __future__ import annotations

import gzip
import os
import zipfile

import pytest

from admin.core import mapgen


def _zip_with(path, arcname: str, data: bytes):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(arcname, data)


# --- extraction ladder -------------------------------------------------------

def test_extract_raw_eden(tmp_path):
    zpath = tmp_path / "w.eden.zip"
    _zip_with(zpath, "1234567890.eden", b"raw eden bytes")
    out = tmp_path / "out"
    out.mkdir()
    result = mapgen.extract_eden(zpath, out)
    assert result is not None
    assert result.read_bytes() == b"raw eden bytes"


def test_extract_gzip_packaged_eden(tmp_path):
    payload = gzip.compress(b"decompressed eden payload")
    zpath = tmp_path / "w.eden.zip"
    _zip_with(zpath, "1234567890.eden.zip", payload)
    out = tmp_path / "out"
    out.mkdir()
    result = mapgen.extract_eden(zpath, out)
    assert result is not None
    assert result.name.endswith(".eden")
    assert result.read_bytes() == payload  # World.ts unwraps the gzip, not us


def test_extract_nested_zip(tmp_path):
    inner = tmp_path / "inner.eden.zip"
    _zip_with(inner, "1234567890.eden", b"nested eden bytes")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.write(inner, "bundle/1234567890.eden.zip")
    out = tmp_path / "out"
    out.mkdir()
    result = mapgen.extract_eden(outer, out)
    assert result is not None
    assert result.read_bytes() == b"nested eden bytes"


def test_extract_ignores_macosx_junk(tmp_path):
    zpath = tmp_path / "w.eden.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("__MACOSX/._1234567890.eden", b"junk")
        z.writestr("1234567890.eden", b"real bytes")
    out = tmp_path / "out"
    out.mkdir()
    result = mapgen.extract_eden(zpath, out)
    assert result.read_bytes() == b"real bytes"


def test_extract_not_a_zip_returns_none(tmp_path):
    fake = tmp_path / "not-a-zip.eden.zip"
    fake.write_bytes(b"not a zip at all")
    out = tmp_path / "out"
    out.mkdir()
    assert mapgen.extract_eden(fake, out) is None


def test_extract_bare_gzip_stream_with_no_outer_zip(tmp_path):
    """world 1584568651 in the real archive: the stored `{id}.eden.zip` is a
    raw gzip stream with no outer real-zip wrap at all — `zipfile.is_zipfile`
    is False for it, so the old code returned None outright. No Python-side
    decompression needed: World.ts detects gzip by magic bytes regardless of
    filename, so this just needs the bytes moved to `dest` as `.eden`."""
    payload = gzip.compress(b"bare gzip payload, no outer zip")
    bare = tmp_path / "1584568651.eden.zip"
    bare.write_bytes(payload)
    out = tmp_path / "out"
    out.mkdir()
    result = mapgen.extract_eden(bare, out)
    assert result is not None
    assert result.name == "1584568651.eden"
    assert result.read_bytes() == payload  # still gzip; World.ts unwraps it


def test_extract_bare_gzip_stream_named_plain_eden(tmp_path):
    payload = gzip.compress(b"bare gzip, already named .eden")
    bare = tmp_path / "1584568651.eden"
    bare.write_bytes(payload)
    out = tmp_path / "out"
    out.mkdir()
    result = mapgen.extract_eden(bare, out)
    assert result is not None
    assert result.name == "1584568651.eden"  # not doubled to .eden.eden


def test_eden_name_for_handles_embedded_eden_substring():
    """world 1770253120 in the real archive: the zip entry's filename has
    world-name/tag words baked in, with an embedded '.eden' substring that
    isn't the actual extension — the real extension is just '.zip'."""
    name = "Eden City 0226a 1770253120.eden retro oldterrain city ikea.zip"
    assert mapgen._eden_name_for(name) == (
        "Eden City 0226a 1770253120.eden retro oldterrain city ikea.eden"
    )


def test_eden_name_for_plain_zip():
    assert mapgen._eden_name_for("world.zip") == "world.eden"


def test_eden_name_for_already_eden_zip():
    assert mapgen._eden_name_for("1234567890.eden.zip") == "1234567890.eden"


# --- find_zip ----------------------------------------------------------------

def test_find_zip_prefers_standard_name(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen.paths, "ASSETS_DIR", tmp_path)
    d = tmp_path / "42"
    d.mkdir()
    (d / "42.eden.zip").write_bytes(b"x")
    (d / "other.zip").write_bytes(b"y")
    assert mapgen.find_zip("42") == d / "42.eden.zip"


def test_find_zip_falls_back_to_any_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen.paths, "ASSETS_DIR", tmp_path)
    d = tmp_path / "42"
    d.mkdir()
    (d / "renamed.zip").write_bytes(b"x")
    assert mapgen.find_zip("42") == d / "renamed.zip"


def test_find_zip_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen.paths, "ASSETS_DIR", tmp_path)
    assert mapgen.find_zip("42") is None


# --- preflight -----------------------------------------------------------

def test_preflight_ok_for_small_raw_eden(tmp_path):
    zpath = tmp_path / "w.eden.zip"
    _zip_with(zpath, "1234567890.eden", b"x" * 1000)
    pf = mapgen.preflight(zpath)
    assert pf.verdict == "ok"
    assert pf.bytes_ == 1000


def test_preflight_too_large_for_big_raw_eden(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen, "TOO_LARGE_BYTES", 500)
    zpath = tmp_path / "w.eden.zip"
    _zip_with(zpath, "1234567890.eden", b"x" * 1000)
    pf = mapgen.preflight(zpath)
    assert pf.verdict == "too_large"


def test_preflight_unknown_for_gzip_packaging(tmp_path):
    zpath = tmp_path / "w.eden.zip"
    _zip_with(zpath, "1234567890.eden.zip", gzip.compress(b"x" * 1000))
    assert mapgen.preflight(zpath).verdict == "unknown"


def test_preflight_unknown_for_non_zip(tmp_path):
    fake = tmp_path / "w.eden.zip"
    fake.write_bytes(b"garbage")
    assert mapgen.preflight(fake).verdict == "unknown"


# --- error classification ---------------------------------------------------

@pytest.mark.parametrize(
    "stderr",
    [
        "RangeError: Invalid typed array length",
        "FATAL ERROR: Array buffer allocation failed",
        "RangeError: Cannot create a string longer than 0x3fffffe7 characters",
        "<--- Last few GCs --->\nJavaScript heap out of memory",
    ],
)
def test_classify_too_large(stderr):
    assert mapgen.classify_error(stderr, 1) == "too_large"


def test_classify_node_error_for_other_nonzero_exit():
    assert mapgen.classify_error("TypeError: something else broke", 1) == "node_error"


def test_classify_unknown_error_for_zero_exit_with_stderr_noise():
    assert mapgen.classify_error("a warning, not fatal", 0) == "unknown_error"


# --- lock ----------------------------------------------------------------

def test_lock_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen.paths, "TEMP_DIR", tmp_path / "mapgen-tmp")
    monkeypatch.setattr(mapgen, "LOCK_FILE", tmp_path / "mapgen-tmp" / ".lock")
    mapgen.acquire_lock()
    assert mapgen.LOCK_FILE.exists()
    mapgen.release_lock()
    assert not mapgen.LOCK_FILE.exists()


def test_lock_refuses_when_held_by_a_live_process(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen.paths, "TEMP_DIR", tmp_path / "mapgen-tmp")
    monkeypatch.setattr(mapgen, "LOCK_FILE", tmp_path / "mapgen-tmp" / ".lock")
    (tmp_path / "mapgen-tmp").mkdir()
    # The parent process is guaranteed alive, signalable, and not us.
    mapgen.LOCK_FILE.write_text(f"{os.getppid()} 999999999999")
    with pytest.raises(mapgen.MapgenLockedError):
        mapgen.acquire_lock()


def test_lock_reclaims_a_stale_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(mapgen.paths, "TEMP_DIR", tmp_path / "mapgen-tmp")
    monkeypatch.setattr(mapgen, "LOCK_FILE", tmp_path / "mapgen-tmp" / ".lock")
    (tmp_path / "mapgen-tmp").mkdir()
    # The holder is alive, but the timestamp is ancient -> stale, reclaim it.
    mapgen.LOCK_FILE.write_text(f"{os.getppid()} 0")
    mapgen.acquire_lock()  # should not raise
    assert str(os.getpid()) in mapgen.LOCK_FILE.read_text()
    mapgen.release_lock()
