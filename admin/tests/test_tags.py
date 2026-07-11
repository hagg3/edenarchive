"""core/tags.py: tag inventory, near-dupe grouping, and bulk retag.

The critical invariant here is the same one frontmatter.py enforces
everywhere else in the app: apply_bulk_retag must never call yaml.dump — it
writes through world.save (format-preserving), unlike the
z_scripts/tag manage/merge_tags.py it replaces.
"""
from __future__ import annotations

from admin.core import tags as tags_mod
from admin.core import world as world_mod


def _make_world(tmp_path, monkeypatch, slug: str, tags: list[str]):
    monkeypatch.setattr(world_mod.paths, "WRITABLE_ROOTS", (tmp_path,))
    monkeypatch.setattr(world_mod.paths, "RUNTIME_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(world_mod.paths, "BACKUP_DIR", tmp_path / ".runtime" / "backups")
    monkeypatch.setattr(world_mod.paths, "UPLOAD_DIR", tmp_path / ".runtime" / "uploads")
    tag_lines = "".join(f"  - {t}\n" for t in tags)
    text = (
        f"---\nlayout: page\nfilename: 1768873101.eden\nworldname: {slug}\n"
        f"publishdate: 2026-01-20\narchivedate: \nfilesize: \"1.0 MB\"\nauthor: \n"
        f"tags:\n{tag_lines}---\n## {slug}\n\nBody text.\n"
    )
    md = tmp_path / f"{slug}.md"
    md.write_text(text, encoding="utf-8")
    return world_mod.load(md)


# --- tag_inventory -----------------------------------------------------------

def test_tag_inventory_counts_and_orders_by_frequency():
    class FakeWorld:
        def __init__(self, slug, tags):
            self.slug = slug
            self.tags = tags

    worlds = [
        FakeWorld("a", ["city", "airport"]),
        FakeWorld("b", ["city"]),
        FakeWorld("c", ["airport", "beach"]),
    ]
    stats = tags_mod.tag_inventory(worlds)
    by_tag = {s.tag: s for s in stats}
    assert by_tag["city"].count == 2
    assert sorted(by_tag["city"].slugs) == ["a", "b"]
    assert by_tag["airport"].count == 2
    assert by_tag["beach"].count == 1
    # sorted by count desc, then tag name
    assert [s.tag for s in stats][:2] == ["airport", "city"]


# --- near_dupe_groups ---------------------------------------------------------

def test_near_dupe_groups_finds_singular_plural_pairs():
    groups = tags_mod.near_dupe_groups(["sport", "sports", "city", "beach"])
    assert ("sport", "sports") in groups


def test_near_dupe_groups_empty_when_nothing_similar():
    assert tags_mod.near_dupe_groups(["city", "beach", "airport"]) == []


# --- load_tag_map --------------------------------------------------------------

def test_load_tag_map_normalizes_case(tmp_path):
    p = tmp_path / "tag_map.yaml"
    p.write_text("Sport: Sports\nHOUSES: house\n", encoding="utf-8")
    tag_map = tags_mod.load_tag_map(p)
    assert tag_map == {"sport": "sports", "houses": "house"}


# --- rewrite_tags --------------------------------------------------------------

def test_rewrite_tags_applies_map_and_dedupes():
    tag_map = {"sport": "sports", "houses": "house"}
    assert tags_mod.rewrite_tags(["sport", "city"], tag_map) == ["sports", "city"]
    # a rename that collides with an existing tag dedupes, keeping first occurrence
    assert tags_mod.rewrite_tags(["sport", "sports"], tag_map) == ["sports"]


def test_rewrite_tags_noop_when_nothing_maps():
    assert tags_mod.rewrite_tags(["city", "beach"], {"sport": "sports"}) == ["city", "beach"]


# --- preview / apply bulk retag -------------------------------------------------

def test_preview_bulk_retag_only_lists_changed_worlds(tmp_path, monkeypatch):
    w1 = _make_world(tmp_path, monkeypatch, "world-one", ["sport", "city"])
    w2 = _make_world(tmp_path, monkeypatch, "world-two", ["beach"])
    tag_map = {"sport": "sports"}
    preview = tags_mod.preview_bulk_retag([w1, w2], tag_map)
    assert [p.slug for p in preview] == ["world-one"]
    assert preview[0].before == ["sport", "city"]
    assert preview[0].after == ["sports", "city"]


def test_apply_bulk_retag_writes_through_frontmatter_render_not_yaml_dump(tmp_path, monkeypatch):
    w = _make_world(tmp_path, monkeypatch, "world-one", ["sport", "city"])
    before_bytes = w.md_path.read_bytes()

    changed = tags_mod.apply_bulk_retag([w], {"sport": "sports"})
    assert changed == ["world-one"]

    after_text = w.md_path.read_text()
    # format-preserving: filesize stays double-quoted, archivedate/author stay
    # empty-with-trailing-space, nothing gets yaml.dump'd into `null` or
    # unquoted/re-wrapped — the exact corruption merge_tags.py causes.
    assert 'filesize: "1.0 MB"' in after_text
    assert "archivedate: \n" in after_text
    assert "archivedate: null" not in after_text
    assert "  - sports\n" in after_text
    assert "  - sport\n" not in after_text

    # frontmatter.render's tag merge preserves the position of tags that
    # survive unchanged and appends renamed/new ones at the end — so "city"
    # (unaffected) stays first and "sports" (renamed from "sport") moves last.
    reloaded = world_mod.load(w.md_path)
    assert reloaded.tags == ["city", "sports"]
    assert after_text != before_bytes.decode()


def test_apply_bulk_retag_leaves_unaffected_worlds_byte_identical(tmp_path, monkeypatch):
    w = _make_world(tmp_path, monkeypatch, "world-two", ["beach"])
    before = w.md_path.read_bytes()
    changed = tags_mod.apply_bulk_retag([w], {"sport": "sports"})
    assert changed == []
    assert w.md_path.read_bytes() == before
