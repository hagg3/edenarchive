"""core/edenserver.py: Eden game-server client (listing parse, search/browse
URL construction, gzip-vs-raw download, size-cap rejection, score_world) plus
the archive-status badge matching server_api._badge computes from the same
index the rest of the app uses.

Network is monkeypatched throughout — no test may touch edengame.net.
"""
from __future__ import annotations

import gzip
import io

import pytest

from admin.app.routers import server_api
from admin.core import edenserver, index as index_mod


# --- parse_listing -----------------------------------------------------------

def test_parse_listing_well_formed():
    text = "1690000001.eden\nFirst World.name\n1690000002.eden\nSecond World.name\n"
    results = edenserver.parse_listing(text)
    assert [r.id for r in results] == ["1690000001", "1690000002"]
    assert results[0].name == "First World"
    assert results[0].timestamp == 1690000001
    assert results[1].name == "Second World"


def test_parse_listing_resyncs_past_a_stray_blank_line():
    text = "1690000001.eden\n\nFirst World.name\n1690000002.eden\nSecond World.name\n"
    results = edenserver.parse_listing(text)
    # The blank line desyncs the first pair (the id line no longer immediately
    # precedes its name line), but the scan must still find the second pair.
    assert len(results) == 1
    assert results[0].id == "1690000002"


def test_parse_listing_ignores_trailing_unpaired_junk():
    text = "1690000001.eden\nFirst World.name\n1690000002.eden\n"
    results = edenserver.parse_listing(text)
    assert len(results) == 1
    assert results[0].id == "1690000001"


def test_parse_listing_empty_body():
    assert edenserver.parse_listing("") == []


# --- score_world ---------------------------------------------------------------

def test_score_world_junk_terms_penalized():
    assert edenserver.score_world("test123", 1700000000) < edenserver.score_world(
        "Downtown City Complex", 1700000000
    )


def test_score_world_structure_and_gameplay_bonus():
    plain = edenserver.score_world("boring", 1700000000)
    structured = edenserver.score_world("Adventure City Complex Quest", 1700000000)
    assert structured > plain


def test_score_world_old_worlds_score_higher():
    old = edenserver.score_world("Some World", 1350000000)  # 2012
    new = edenserver.score_world("Some World", 1700000000)  # 2023
    assert old > new


def test_score_world_red_marker_is_heavily_penalized():
    assert edenserver.score_world("Weird 'red' World", 1700000000) == -10


# --- search / browse URL + parsing --------------------------------------------

class _FakeTextResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


def test_search_hits_list_url_with_query(monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        return _FakeTextResponse("1690000001.eden\nA World.name\n")

    monkeypatch.setattr("requests.get", fake_get)
    results = edenserver.search("A World", edenserver.SERVERS["current"])
    assert "search=A+World" in captured["url"]
    assert results[0].name == "A World"


def test_browse_hits_list_url_with_start_and_sort(monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        return _FakeTextResponse("")

    monkeypatch.setattr("requests.get", fake_get)
    edenserver.browse(40, edenserver.SERVERS["legacy"], sort=2)
    assert "start=40" in captured["url"]
    assert "sort=2" in captured["url"]
    assert captured["url"].startswith(edenserver.SERVERS["legacy"].list_url)


# --- fetch_preview -------------------------------------------------------------

class _FakeBinResponse:
    def __init__(self, content: bytes, ok=True):
        self.content = content
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            import requests
            raise requests.RequestException("boom")


def test_fetch_preview_returns_none_on_non_png(monkeypatch):
    monkeypatch.setattr("requests.get", lambda url, timeout=None: _FakeBinResponse(b"not a png"))
    assert edenserver.fetch_preview("1", edenserver.SERVERS["current"]) is None


def test_fetch_preview_returns_bytes_on_png(monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    monkeypatch.setattr("requests.get", lambda url, timeout=None: _FakeBinResponse(png))
    assert edenserver.fetch_preview("1", edenserver.SERVERS["current"]) == png


def test_fetch_preview_any_falls_back_to_legacy(monkeypatch):
    png = b"\x89PNG\r\n\x1a\nrest"

    def fake_get(url, timeout=None):
        if "files2." in url:
            return _FakeBinResponse(b"", ok=False)
        return _FakeBinResponse(png)

    monkeypatch.setattr("requests.get", fake_get)
    data, server = edenserver.fetch_preview_any("1")
    assert data == png
    assert server == "legacy"


# --- download: gzip vs raw, size cap -------------------------------------------

class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes], content_length: str | None = None):
        self._chunks = chunks
        self.headers = {"content-length": content_length} if content_length else {}

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_raw_writes_bytes_unmodified(tmp_path, monkeypatch):
    payload = b"raw eden bytes, not gzip"
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeStreamResponse([payload]))
    dest = tmp_path / "1.eden"
    edenserver.download("1", edenserver.SERVERS["current"], dest)
    assert dest.read_bytes() == payload
    assert not dest.with_name(dest.name + ".download.tmp").exists()
    assert not dest.with_name(dest.name + ".tmp").exists()


def test_download_gzip_decompresses(tmp_path, monkeypatch):
    raw = b"decompressed world contents" * 100
    gz = gzip.compress(raw)
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeStreamResponse([gz]))
    dest = tmp_path / "1.eden"
    edenserver.download("1", edenserver.SERVERS["current"], dest)
    assert dest.read_bytes() == raw


def test_download_rejects_oversized_content_length(tmp_path, monkeypatch):
    monkeypatch.setattr(edenserver, "MAX_DOWNLOAD_BYTES", 100)
    monkeypatch.setattr(
        "requests.get", lambda *a, **k: _FakeStreamResponse([b"x" * 10], content_length="1000")
    )
    dest = tmp_path / "1.eden"
    with pytest.raises(edenserver.DownloadTooLarge):
        edenserver.download("1", edenserver.SERVERS["current"], dest)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".download.tmp").exists()


def test_download_rejects_oversized_stream_without_content_length(tmp_path, monkeypatch):
    monkeypatch.setattr(edenserver, "MAX_DOWNLOAD_BYTES", 10)
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeStreamResponse([b"x" * 5, b"y" * 20]))
    dest = tmp_path / "1.eden"
    with pytest.raises(edenserver.DownloadTooLarge):
        edenserver.download("1", edenserver.SERVERS["current"], dest)
    assert not dest.exists()


def test_download_rejects_gzip_bomb_after_decompression(tmp_path, monkeypatch):
    raw = b"y" * 10_000
    gz = gzip.compress(raw)
    monkeypatch.setattr(edenserver, "MAX_DOWNLOAD_BYTES", 100)
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeStreamResponse([gz]))
    dest = tmp_path / "1.eden"
    with pytest.raises(edenserver.DownloadTooLarge):
        edenserver.download("1", edenserver.SERVERS["current"], dest)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".download.tmp").exists()
    assert not dest.with_name(dest.name + ".tmp").exists()


# --- badge matching (server_api._badge) ----------------------------------------

def _conn_with_world(tmp_path, *, slug, world_id, worldname, norm_name, base_name):
    conn = index_mod.connect(tmp_path / "index.db")
    conn.execute(
        "INSERT INTO worlds (slug, md_path, world_id, worldname, norm_name, base_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (slug, f"_worlds/{slug}.md", world_id, worldname, norm_name, base_name),
    )
    conn.commit()
    return conn


def test_badge_exact_world_id_match(tmp_path):
    conn = _conn_with_world(
        tmp_path, slug="my-city", world_id="1700000000", worldname="My City",
        norm_name="my city", base_name="my city",
    )
    sw = edenserver.ServerWorld(id="1700000000", name="Some Other Name", timestamp=1700000000)
    kind, slug, label = server_api._badge(conn, sw)
    assert kind == "archived"
    assert slug == "my-city"


def test_badge_near_name_match(tmp_path):
    conn = _conn_with_world(
        tmp_path, slug="my-city", world_id="1700000000", worldname="My City",
        norm_name="my city", base_name="my city",
    )
    sw = edenserver.ServerWorld(id="1999999999", name="My City v2", timestamp=1999999999)
    kind, slug, label = server_api._badge(conn, sw)
    assert kind == "possibly archived"
    assert slug == "my-city"


def test_badge_no_match(tmp_path):
    conn = _conn_with_world(
        tmp_path, slug="my-city", world_id="1700000000", worldname="My City",
        norm_name="my city", base_name="my city",
    )
    sw = edenserver.ServerWorld(id="1999999999", name="Completely Unrelated Place", timestamp=1999999999)
    kind, slug, label = server_api._badge(conn, sw)
    assert kind == ""
    assert slug == ""
