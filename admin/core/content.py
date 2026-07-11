"""_posts / _articles: parse, list, save, rename, delete.

Reuses frontmatter.py's format-preserving parse/render — the same machinery
that protects _worlds/ front matter works here too, since CANONICAL_ORDER and
ALWAYS_QUOTED only affect keys neither posts nor articles use (worldname,
filesize, tags), and the quoting-preservation logic (keep whatever the
original line did) is generic, not world-specific.

Much smaller collection than _worlds/ (3 posts + 4 articles vs. 768 worlds),
so unlike world.py there's no SQLite index for this — load_all() just globs
the directory fresh each time, which is instant at this size.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter as fm
from . import paths
from . import world as world_mod

POST_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")

DIR_FOR = {"post": paths.POSTS_DIR, "article": paths.ARTICLES_DIR}
LAYOUT_FOR = {"post": "post", "article": "page"}


class ContentError(ValueError):
    pass


@dataclass
class ContentItem:
    kind: str  # "post" | "article"
    filename: str
    path: Path
    doc: fm.Document

    @property
    def title(self) -> str:
        return str(self.doc.data.get("title") or "").strip()

    @property
    def author(self) -> str:
        return str(self.doc.data.get("author") or "").strip()

    @property
    def date(self) -> str:
        v = self.doc.data.get("date")
        return str(v).strip() if v is not None else ""

    @property
    def body(self) -> str:
        return self.doc.body

    @property
    def slug(self) -> str:
        return Path(self.filename).stem

    @property
    def filename_date(self) -> str | None:
        """The date Jekyll actually uses for a post's permalink/sort order —
        from the *filename*, not the front-matter `date:` field, which can
        differ (confirmed in the real corpus: 2026-02-09-a-b-c.md has
        `date: 2013-05-31` inside its front matter). Editing `date:` alone
        does not move a post in time; only renaming the file does."""
        if self.kind != "post":
            return None
        m = POST_FILENAME_RE.match(self.filename)
        return m.group(1) if m else None


def _kind_dir(kind: str) -> Path:
    if kind not in DIR_FOR:
        raise ContentError(f"unknown content kind: {kind!r}")
    return DIR_FOR[kind]


def load(kind: str, filename: str) -> ContentItem:
    if not paths.SLUG_RE.match(Path(filename).stem) or ".." in filename:
        raise ContentError(f"invalid filename: {filename!r}")
    path = _kind_dir(kind) / filename
    doc = fm.parse(path)
    return ContentItem(kind=kind, filename=filename, path=path, doc=doc)


def load_all(kind: str) -> list[ContentItem]:
    return [load(kind, p.name) for p in sorted(_kind_dir(kind).glob("*.md"), reverse=True)]


def filename_for(kind: str, *, date: str = "", title: str) -> str:
    slug = world_mod.slugify(title)
    if not slug:
        raise ContentError("title must produce a non-empty slug")
    if kind == "post":
        if not paths.DATE_RE.match(date):
            raise ContentError("posts need a valid YYYY-MM-DD date for the filename")
        return f"{date}-{slug}.md"
    return f"{slug}.md"


def create(kind: str, *, title: str, author: str, date: str, body: str) -> ContentItem:
    filename = filename_for(kind, date=date, title=title)
    path = _kind_dir(kind) / filename
    if path.exists():
        raise ContentError(f"{filename} already exists")

    layout = LAYOUT_FOR[kind]
    lines = [f"layout: {layout}", f'title: "{title}"']
    if kind == "post":
        lines.append(f"date: {date}")
    if author:
        lines.append(f"author: {author}")
    elif kind == "article":
        # Match the corpus convention (all 4 articles have an author line,
        # even if a generic one) rather than omitting the key entirely.
        lines.append("author: ")
    text = "\n".join(["---", *lines, "---"]) + world_mod.normalize_body(body)

    path = paths.assert_writable(path)
    path.write_text(text, encoding="utf-8", newline="\n")
    return load(kind, filename)


def save(item: ContentItem, updates: dict, body: str | None = None) -> bool:
    new_body = None if body is None else world_mod.normalize_body(body)
    return fm.save(item.path, item.doc, updates, new_body)


def rename(item: ContentItem, new_filename: str) -> ContentItem:
    """Renames the file on disk — needed when a post's date (not just its
    front-matter `date:` field) or an article's title/slug changes. Working
    tree only, same as every other write in admin/."""
    if new_filename == item.filename:
        return item
    new_path = _kind_dir(item.kind) / new_filename
    if new_path.exists():
        raise ContentError(f"{new_filename} already exists")
    old_path = paths.assert_writable(item.path)
    new_path = paths.assert_writable(new_path)
    old_path.rename(new_path)
    return load(item.kind, new_filename)


def delete(item: ContentItem) -> None:
    path = paths.assert_writable(item.path)
    path.unlink()
