"""The gating test: render(parse(f), {}) must be byte-identical to f, for every
markdown file in the archive. If this does not pass 775/775, no write feature in
the admin app is safe to ship.
"""
from __future__ import annotations

import pytest

from admin.core import frontmatter as fm
from admin.core import paths


def _corpus():
    files = []
    for d in (paths.WORLDS_DIR, paths.ARTICLES_DIR, paths.POSTS_DIR):
        if d.exists():
            files.extend(sorted(d.glob("*.md")))
    return files


CORPUS = _corpus()


def test_corpus_is_present():
    assert len(CORPUS) >= 775, f"expected the full corpus, found {len(CORPUS)}"


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_roundtrip_is_byte_identical(path):
    doc = fm.parse(path)
    assert fm.render(doc, {}) == path.read_text(encoding="utf-8")


def test_noop_update_is_byte_identical():
    """Re-writing a key with the value it already has must not change bytes."""
    for path in CORPUS[:50]:
        doc = fm.parse(path)
        updates = {k: doc.data.get(k) for k in ("worldname", "author", "tags") if k in doc.key_order}
        assert fm.render(doc, updates) == path.read_text(encoding="utf-8"), path


def test_empty_value_on_absent_key_is_noop(tmp_path):
    src = tmp_path / "w.md"
    src.write_text("---\nlayout: page\nauthor: \ntags:\n  - a\n---\n\nBody\n")
    doc = fm.parse(src)
    assert fm.render(doc, {"archivedate": ""}) == src.read_text()


def test_insert_respects_canonical_order(tmp_path):
    src = tmp_path / "w.md"
    src.write_text(
        "---\nlayout: page\nfilename: 1315348100.eden\nworldname: X\n"
        "publishdate: 2011-09-07\nauthor: Dante\ntags:\n  - sport\n---\n\nBody\n"
    )
    doc = fm.parse(src)
    out = fm.render(doc, {"archivedate": "2024-01-15"})
    lines = out.split("\n")
    assert lines[lines.index("publishdate: 2011-09-07") + 1] == "archivedate: 2024-01-15"
    assert "author: Dante" in lines


def test_filesize_is_always_quoted(tmp_path):
    src = tmp_path / "w.md"
    src.write_text("---\nlayout: page\nfilesize: \"1.0 MB\"\ntags:\n---\n\nBody\n")
    doc = fm.parse(src)
    assert 'filesize: "3.5 MB"' in fm.render(doc, {"filesize": "3.5 MB"})


def test_tag_append_preserves_existing_order(tmp_path):
    src = tmp_path / "w.md"
    src.write_text("---\nlayout: page\ntags:\n  - b\n  - a\n---\n\nBody\n")
    doc = fm.parse(src)
    out = fm.render(doc, {"tags": ["a", "b", "new"]})
    assert "tags:\n  - b\n  - a\n  - new\n" in out


def test_body_passes_through_untouched(tmp_path):
    src = tmp_path / "w.md"
    body = "\n\n## Map\n\n![map](map.png)\n\n\n"
    src.write_text("---\nlayout: page\nauthor: Z\ntags:\n  - x\n---" + body)
    doc = fm.parse(src)
    assert fm.render(doc, {"author": "Q"}).endswith(body)


def test_body_override_replaces_content(tmp_path):
    src = tmp_path / "w.md"
    src.write_text("---\nlayout: page\nauthor: Z\ntags:\n  - x\n---\n\nOld body\n")
    doc = fm.parse(src)
    out = fm.render(doc, {}, body="\nNew body\n")
    assert out == "---\nlayout: page\nauthor: Z\ntags:\n  - x\n---\nNew body\n"


def test_body_override_none_is_original_body(tmp_path):
    src = tmp_path / "w.md"
    src.write_text("---\nlayout: page\nauthor: Z\ntags:\n  - x\n---\n\nOld body\n")
    doc = fm.parse(src)
    assert fm.render(doc, {}, body=None) == src.read_text()
