"""M1 world-editing behavior: core/world.save() on top of frontmatter.save().

These exercise the same two invariants verified live against the real repo in
M1 (see ADMIN_APP_PLAN.md verification items 2-3), but against throwaway
fixtures so the corpus is never touched by the test suite.
"""
from __future__ import annotations

from admin.core import world as world_mod


def _make_world(tmp_path, monkeypatch, text: str):
    monkeypatch.setattr(world_mod.paths, "WRITABLE_ROOTS", (tmp_path,))
    monkeypatch.setattr(world_mod.paths, "RUNTIME_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(world_mod.paths, "BACKUP_DIR", tmp_path / ".runtime" / "backups")
    monkeypatch.setattr(world_mod.paths, "UPLOAD_DIR", tmp_path / ".runtime" / "uploads")
    md = tmp_path / "070032-980002.md"
    md.write_text(text, encoding="utf-8")
    return world_mod.load(md)


FIXTURE = (
    "---\nlayout: page\nfilename: 1768873101.eden\nworldname: 070032 980002\n"
    "publishdate: 2026-01-20\narchivedate: \nfilesize: \"3.5 MB\"\nauthor: \n"
    "tags:\n  - normalterrain\n  - city\n  - unknown\n  - airport\n---\n"
    "## 070032 980002\n\nBody text.\n"
)


def test_noop_save_produces_no_bytes_change(tmp_path, monkeypatch):
    w = _make_world(tmp_path, monkeypatch, FIXTURE)
    before = w.md_path.read_bytes()
    changed = world_mod.save(
        w,
        {
            "worldname": w.worldname,
            "author": w.author,
            "publishdate": w.publishdate,
            "archivedate": w.archivedate,
            "filesize": w.filesize,
            "tags": w.tags,
        },
        body=w.body,
    )
    assert changed is False
    assert w.md_path.read_bytes() == before


def test_adding_one_tag_is_a_single_line_diff(tmp_path, monkeypatch):
    w = _make_world(tmp_path, monkeypatch, FIXTURE)
    changed = world_mod.save(w, {"tags": [*w.tags, "newtag"]}, body=w.body)
    assert changed is True
    expected = FIXTURE.replace("  - airport\n---", "  - airport\n  - newtag\n---")
    assert w.md_path.read_text() == expected


def test_body_edit_is_isolated_from_front_matter(tmp_path, monkeypatch):
    w = _make_world(tmp_path, monkeypatch, FIXTURE)
    world_mod.save(w, {}, body="## 070032 980002\n\nRewritten body.")
    reloaded = world_mod.load(w.md_path)
    assert reloaded.body.strip() == "## 070032 980002\n\nRewritten body."
    assert reloaded.worldname == "070032 980002"  # front matter untouched


def test_normalize_body_variants():
    assert world_mod.normalize_body("hello") == "\nhello\n"
    assert world_mod.normalize_body("\n\nhello\n\n\n") == "\nhello\n"
    assert world_mod.normalize_body("a\r\nb\r\n") == "\na\nb\n"
    assert world_mod.normalize_body("") == "\n"
    assert world_mod.normalize_body("   \n  ") == "\n"
