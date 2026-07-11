"""core/importer.py: staged upload -> similarity check -> commit.

De-interactivized z_add_world.py:import_one_file() — these tests exercise the
same behaviors the original interactive script had (naming-convention
parsing, world id from the eden filename, never overwriting an existing .md,
the exact hand-written front-matter shape) plus the new staging/warning
machinery M6 adds on top.
"""
from __future__ import annotations

import zipfile

import pytest

from admin.core import importer
from admin.core import index as index_mod


WORLD_ID = "1700000000"


def _wire(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    worlds = tmp_path / "_worlds"
    runtime = tmp_path / ".runtime"
    assets.mkdir()
    worlds.mkdir()
    for mod in (importer.paths, index_mod.paths):
        monkeypatch.setattr(mod, "ASSETS_DIR", assets, raising=False)
        monkeypatch.setattr(mod, "WORLDS_DIR", worlds, raising=False)
        monkeypatch.setattr(mod, "RUNTIME_DIR", runtime, raising=False)
        monkeypatch.setattr(mod, "BACKUP_DIR", runtime / "backups", raising=False)
        monkeypatch.setattr(mod, "UPLOAD_DIR", runtime / "uploads", raising=False)
        monkeypatch.setattr(mod, "WRITABLE_ROOTS", (assets, worlds, runtime), raising=False)
    monkeypatch.setattr(importer, "_try_download_preview", lambda world_id, dest: False)
    return assets, worlds


def _zip_bytes(arcname: str, data: bytes) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(arcname, data)
    return buf.getvalue()


# --- naming convention --------------------------------------------------------

def test_parse_naming_convention_full():
    name, wid, tags = importer.parse_naming_convention(
        f"Cool City {WORLD_ID} city, skyscrapers.eden.zip"
    )
    assert name == "Cool City"
    assert wid == WORLD_ID
    assert tags == ["city", "skyscrapers"]


def test_parse_naming_convention_no_id():
    name, wid, tags = importer.parse_naming_convention("just_a_file.eden.zip")
    assert (name, wid, tags) == (None, None, [])


def test_parse_naming_convention_id_only():
    name, wid, tags = importer.parse_naming_convention(f"{WORLD_ID}.eden.zip")
    assert wid == WORLD_ID
    assert name is None


# --- stage ---------------------------------------------------------------------

def test_stage_zip_with_raw_eden_and_bundled_preview(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    payload = b"raw eden payload bytes"
    data = _zip_bytes(f"{WORLD_ID}.eden", payload)
    # add a bundled preview image too
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{WORLD_ID}.eden", payload)
        z.writestr("preview.png", b"fake png bytes")
    data = buf.getvalue()

    token = importer.receive_upload(data, f"Cool City {WORLD_ID}.eden.zip")
    staged = importer.stage(token, f"Cool City {WORLD_ID}.eden.zip")

    assert staged.error is None
    assert staged.world_id == WORLD_ID
    assert staged.worldname == "Cool City"
    assert staged.eden_path.read_bytes() == payload
    assert len(staged.preview_paths) == 1
    assert staged.publishdate is not None
    assert staged.filesize is not None
    assert staged.zip_sha256


def test_stage_raw_eden_no_outer_zip(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    payload = b"a raw eden file with no zip wrapper at all"
    token = importer.receive_upload(payload, f"{WORLD_ID}.eden")
    staged = importer.stage(token, f"{WORLD_ID}.eden")
    assert staged.world_id == WORLD_ID
    assert staged.eden_path.read_bytes() == payload


def test_stage_no_id_anywhere_is_an_error(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    token = importer.receive_upload(b"whatever", "no_id_here.eden")
    staged = importer.stage(token, "no_id_here.eden")
    assert staged.world_id is None
    assert staged.error is not None


def test_discard_removes_staged_files(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    token = importer.receive_upload(_zip_bytes(f"{WORLD_ID}.eden", b"x"), "w.eden.zip")
    importer.stage(token, "w.eden.zip")
    assert list(importer.paths.UPLOAD_DIR.glob(f"{token}*"))
    importer.discard(token)
    assert not list(importer.paths.UPLOAD_DIR.glob(f"{token}*"))


# --- check_against_archive ------------------------------------------------------

def _make_conn(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    conn = index_mod.connect(tmp_path / ".runtime" / "index.db")
    return conn


def _insert_world(conn, slug, *, world_id="", worldname="", norm_name="", base_name="",
                   zip_sha256=None, payload_sha256=None):
    conn.execute(
        "INSERT INTO worlds (slug, md_path, world_id, worldname, norm_name, base_name, "
        "zip_sha256, payload_sha256) VALUES (?,?,?,?,?,?,?,?)",
        (slug, f"_worlds/{slug}.md", world_id, worldname, norm_name, base_name,
         zip_sha256, payload_sha256),
    )
    conn.commit()


def test_already_archived_is_a_hard_block(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    _insert_world(conn, "existing-world", world_id=WORLD_ID, worldname="Existing World")
    staged = importer.StagedImport(
        token="x", staged_path=tmp_path / "x.zip", original_filename="x.zip",
        eden_path=None, world_id=WORLD_ID,
    )
    warnings = importer.check_against_archive(staged, conn)
    assert len(warnings) == 1
    assert warnings[0].kind == "already_archived"
    assert warnings[0].blocking is True


def test_identical_payload_warning(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    _insert_world(conn, "twin", world_id="1600000000", worldname="Twin", payload_sha256="ph1")
    staged = importer.StagedImport(
        token="x", staged_path=tmp_path / "x.zip", original_filename="x.zip",
        eden_path=None, world_id=WORLD_ID, payload_sha256="ph1", zip_sha256="different",
    )
    warnings = importer.check_against_archive(staged, conn)
    kinds = {w.kind for w in warnings}
    assert "identical_payload" in kinds
    assert "identical_zip" not in kinds  # payload match supersedes


def test_identical_zip_warning_when_payload_unknown(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    _insert_world(conn, "twin", world_id="1600000000", worldname="Twin", zip_sha256="zh1")
    staged = importer.StagedImport(
        token="x", staged_path=tmp_path / "x.zip", original_filename="x.zip",
        eden_path=None, world_id=WORLD_ID, zip_sha256="zh1",
    )
    warnings = importer.check_against_archive(staged, conn)
    assert any(w.kind == "identical_zip" for w in warnings)


def test_similar_name_warning(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    _insert_world(
        conn, "downtown-skyline", world_id="1600000000", worldname="Downtown Skyline",
        norm_name="downtown skyline", base_name="downtown skyline",
    )
    staged = importer.StagedImport(
        token="x", staged_path=tmp_path / "x.zip", original_filename="x.zip",
        eden_path=None, world_id=WORLD_ID, worldname="Downtown Skylines",
    )
    warnings = importer.check_against_archive(staged, conn)
    assert any(w.kind == "similar_name" for w in warnings)


def test_no_warnings_for_a_genuinely_new_world(tmp_path, monkeypatch):
    conn = _make_conn(tmp_path, monkeypatch)
    _insert_world(
        conn, "unrelated", world_id="1600000000", worldname="Unrelated Thing",
        norm_name="unrelated thing", base_name="unrelated thing",
    )
    staged = importer.StagedImport(
        token="x", staged_path=tmp_path / "x.zip", original_filename="x.zip",
        eden_path=None, world_id=WORLD_ID, worldname="Completely Different Castle",
    )
    assert importer.check_against_archive(staged, conn) == []


# --- commit ----------------------------------------------------------------------

def test_commit_writes_asset_dir_zip_and_md(tmp_path, monkeypatch):
    assets, worlds = _wire(tmp_path, monkeypatch)
    payload = b"raw eden payload"
    token = importer.receive_upload(_zip_bytes(f"{WORLD_ID}.eden", payload), f"{WORLD_ID}.eden.zip")
    staged = importer.stage(token, f"{WORLD_ID}.eden.zip")

    slug = importer.commit(
        staged, worldname="My New World", author="Tester", archivedate="2026-07-11", tags=["city", "test"]
    )

    assert slug == "my-new-world"
    md_path = worlds / "my-new-world.md"
    assert md_path.exists()
    text = md_path.read_text()
    assert text.startswith("---\nlayout: page\n")
    assert f"filename: {WORLD_ID}.eden\n" in text
    assert "worldname: My New World\n" in text
    assert 'filesize: "0.0 MB"' in text
    assert "author: Tester\n" in text
    assert "  - city\n  - test\n" in text
    assert text.endswith(")\n")  # exactly one trailing newline, like z_add_world.py's output

    zip_path = assets / WORLD_ID / f"{WORLD_ID}.eden.zip"
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as z:
        assert z.read(f"{WORLD_ID}.eden") == payload

    marker = assets / WORLD_ID / "My New World"
    assert marker.exists() and marker.stat().st_size == 0

    # staging area cleaned up after a successful commit
    assert not list(importer.paths.UPLOAD_DIR.glob(f"{token}*"))


def test_commit_never_overwrites_an_existing_md_for_the_same_slug(tmp_path, monkeypatch):
    assets, worlds = _wire(tmp_path, monkeypatch)
    existing = worlds / "my-new-world.md"
    existing.write_text("--- existing content, must survive ---", encoding="utf-8")

    token = importer.receive_upload(
        _zip_bytes(f"{WORLD_ID}.eden", b"payload"), f"{WORLD_ID}.eden.zip"
    )
    staged = importer.stage(token, f"{WORLD_ID}.eden.zip")
    importer.commit(staged, worldname="My New World", author="", archivedate="", tags=[])

    assert existing.read_text() == "--- existing content, must survive ---"
    # but the asset dir/zip still get written
    assert (assets / WORLD_ID / f"{WORLD_ID}.eden.zip").exists()


def test_commit_requires_a_world_id(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    token = importer.receive_upload(b"no id in this filename", "mystery.eden")
    staged = importer.stage(token, "mystery.eden")
    with pytest.raises(importer.ImporterError):
        importer.commit(staged, worldname="X", author="", archivedate="", tags=[])


def test_commit_requires_a_worldname(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    token = importer.receive_upload(_zip_bytes(f"{WORLD_ID}.eden", b"x"), f"{WORLD_ID}.eden.zip")
    staged = importer.stage(token, f"{WORLD_ID}.eden.zip")
    with pytest.raises(importer.ImporterError):
        importer.commit(staged, worldname="   ", author="", archivedate="", tags=[])


def test_commit_uses_bundled_preview_image_as_map(tmp_path, monkeypatch):
    assets, _ = _wire(tmp_path, monkeypatch)
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{WORLD_ID}.eden", b"payload")
        z.writestr("bundled_map.png", b"a fake but larger png" * 10)
    token = importer.receive_upload(buf.getvalue(), f"{WORLD_ID}.eden.zip")
    staged = importer.stage(token, f"{WORLD_ID}.eden.zip")
    importer.commit(staged, worldname="Has Map", author="", archivedate="", tags=[])

    map_path = assets / WORLD_ID / "map.png"
    assert map_path.exists()
    assert map_path.read_bytes() == b"a fake but larger png" * 10
