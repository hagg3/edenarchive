"""core/content.py: _posts / _articles parse, create, edit, rename, delete.

Reuses frontmatter.py's format-preserving save, so the same no-op-safe and
targeted-diff guarantees M1 proved for _worlds/*.md apply here too.
"""
from __future__ import annotations

import pytest

from admin.core import content as content_mod
from admin.core import frontmatter as fm


def _wire(tmp_path, monkeypatch):
    posts = tmp_path / "_posts"
    articles = tmp_path / "_articles"
    posts.mkdir()
    articles.mkdir()
    monkeypatch.setattr(content_mod.paths, "POSTS_DIR", posts)
    monkeypatch.setattr(content_mod.paths, "ARTICLES_DIR", articles)
    monkeypatch.setattr(content_mod, "DIR_FOR", {"post": posts, "article": articles})
    monkeypatch.setattr(content_mod.paths, "WRITABLE_ROOTS", (tmp_path,))
    monkeypatch.setattr(content_mod.paths, "RUNTIME_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(content_mod.paths, "BACKUP_DIR", tmp_path / ".runtime" / "backups")
    return posts, articles


POST_FIXTURE = (
    "---\nlayout: post\ntitle: \"Moof Hacks: Tips and Tricks\"\n"
    "date: 2021-08-17\nauthor: Andy500\n---\nBody text.\n"
)

ARTICLE_FIXTURE = (
    "---\nlayout: page\ntitle: Santa Ines\ndate: 2026-01-01\nauthor: Sam H\n---\n"
    "\n2026-01-01\n\nSam H\n"
)


def test_load_post_reads_fields(tmp_path, monkeypatch):
    posts, _ = _wire(tmp_path, monkeypatch)
    (posts / "2021-08-17-moof-hacks.md").write_text(POST_FIXTURE, encoding="utf-8")
    item = content_mod.load("post", "2021-08-17-moof-hacks.md")
    assert item.title == "Moof Hacks: Tips and Tricks"
    assert item.author == "Andy500"
    assert item.date == "2021-08-17"
    assert item.filename_date == "2021-08-17"


def test_load_all_posts_sorted_newest_first(tmp_path, monkeypatch):
    posts, _ = _wire(tmp_path, monkeypatch)
    (posts / "2020-01-01-old.md").write_text(POST_FIXTURE, encoding="utf-8")
    (posts / "2024-01-01-new.md").write_text(POST_FIXTURE, encoding="utf-8")
    items = content_mod.load_all("post")
    assert [i.filename for i in items] == ["2024-01-01-new.md", "2020-01-01-old.md"]


def test_article_filename_date_is_none():
    # filename_date only makes sense for posts (Jekyll date-prefix convention)
    item = content_mod.ContentItem(kind="article", filename="x.md", path=None, doc=None)
    assert item.filename_date is None


# --- create --------------------------------------------------------------------

def test_create_post_produces_dated_filename(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    item = content_mod.create(
        "post", title="A New Post!", author="Tester", date="2026-03-01", body="Hello."
    )
    assert item.filename == "2026-03-01-a-new-post.md"
    assert item.title == "A New Post!"
    assert item.body.strip() == "Hello."


def test_create_article_has_no_date_prefix(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    item = content_mod.create("article", title="A Wiki Page", author="", date="", body="Text.")
    assert item.filename == "a-wiki-page.md"
    assert item.author == ""


def test_create_refuses_to_overwrite(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    content_mod.create("post", title="Dup", author="", date="2026-01-01", body="a")
    with pytest.raises(content_mod.ContentError):
        content_mod.create("post", title="Dup", author="", date="2026-01-01", body="b")


def test_create_post_requires_valid_date(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    with pytest.raises(content_mod.ContentError):
        content_mod.create("post", title="X", author="", date="not-a-date", body="a")


# --- save ------------------------------------------------------------------------

def test_noop_save_produces_no_bytes_change(tmp_path, monkeypatch):
    posts, _ = _wire(tmp_path, monkeypatch)
    p = posts / "2021-08-17-moof-hacks.md"
    p.write_text(POST_FIXTURE, encoding="utf-8")
    item = content_mod.load("post", p.name)
    before = p.read_bytes()
    changed = content_mod.save(
        item, {"title": item.title, "author": item.author, "date": item.date}, body=item.body
    )
    assert changed is False
    assert p.read_bytes() == before


def test_editing_author_is_a_targeted_diff(tmp_path, monkeypatch):
    posts, _ = _wire(tmp_path, monkeypatch)
    p = posts / "2021-08-17-moof-hacks.md"
    p.write_text(POST_FIXTURE, encoding="utf-8")
    item = content_mod.load("post", p.name)
    content_mod.save(item, {"author": "New Author"})
    assert p.read_text() == POST_FIXTURE.replace("author: Andy500", "author: New Author")


def test_malformed_front_matter_still_loads_and_flags(tmp_path, monkeypatch):
    _, articles = _wire(tmp_path, monkeypatch)
    p = articles / "creatures.md"
    p.write_text(
        "---\nlayout: page\ntitle: Creatures\ndate: 2026-01-01\n"
        "Eden World Builder Wiki\n---\n\nBody.\n",
        encoding="utf-8",
    )
    item = content_mod.load("article", "creatures.md")
    assert item.doc.malformed is True
    assert item.title == ""  # data is empty for a malformed doc


# --- rename ----------------------------------------------------------------------

def test_rename_moves_the_file(tmp_path, monkeypatch):
    posts, _ = _wire(tmp_path, monkeypatch)
    p = posts / "2021-08-17-moof-hacks.md"
    p.write_text(POST_FIXTURE, encoding="utf-8")
    item = content_mod.load("post", p.name)
    renamed = content_mod.rename(item, "2022-01-01-moof-hacks.md")
    assert renamed.filename == "2022-01-01-moof-hacks.md"
    assert not p.exists()
    assert (posts / "2022-01-01-moof-hacks.md").exists()


def test_rename_refuses_to_clobber_existing_file(tmp_path, monkeypatch):
    posts, _ = _wire(tmp_path, monkeypatch)
    (posts / "a.md").write_text(POST_FIXTURE, encoding="utf-8")
    (posts / "b.md").write_text(POST_FIXTURE, encoding="utf-8")
    item = content_mod.load("post", "a.md")
    with pytest.raises(content_mod.ContentError):
        content_mod.rename(item, "b.md")


def test_rename_to_same_name_is_a_noop(tmp_path, monkeypatch):
    posts, _ = _wire(tmp_path, monkeypatch)
    p = posts / "a.md"
    p.write_text(POST_FIXTURE, encoding="utf-8")
    item = content_mod.load("post", "a.md")
    renamed = content_mod.rename(item, "a.md")
    assert renamed.filename == "a.md"
    assert p.exists()


# --- delete ------------------------------------------------------------------------

def test_delete_removes_the_file(tmp_path, monkeypatch):
    posts, _ = _wire(tmp_path, monkeypatch)
    p = posts / "a.md"
    p.write_text(POST_FIXTURE, encoding="utf-8")
    item = content_mod.load("post", "a.md")
    content_mod.delete(item)
    assert not p.exists()
