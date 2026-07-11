"""The World record: front matter + the assets on disk that go with it."""
from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import frontmatter as fm
from . import paths

# Stray 0-byte marker file z_add_world.py drops in every asset dir, named after
# the world. Not an asset; the indexer ignores it.
ASSET_FILENAMES = {"map.png"}

VERSION_TOKENS = re.compile(
    r"\b(v\s?\d+(\.\d+)*[a-z]?\d*|version\s?\d+|final|fixed|updated|new|old|revised"
    r"|remake|remaster|redux|complete|wip|beta|copy|rc\d*|part\s?\d+|pt\s?\d+"
    r"|ep\s?\d+|ii|iii|iv|\(\d+\)|\d+)$"
)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "-", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def bytes_to_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def normalize_name(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_version(norm: str) -> tuple[str, list[str]]:
    """`"city v2 final"` -> `("city", ["v2", "final"])`. Never strips down to
    fewer than 3 characters, so a world literally named "2" survives."""
    base, tokens = norm, []
    while True:
        m = VERSION_TOKENS.search(base)
        if not m:
            break
        candidate = base[: m.start()].strip()
        if len(candidate) < 3:
            break
        tokens.insert(0, m.group(0).strip())
        base = candidate
    return base, tokens


@dataclass
class World:
    slug: str
    md_path: Path
    doc: fm.Document
    world_id: str | None = None
    issues: list[str] = field(default_factory=list)

    # --- front matter accessors -------------------------------------------
    @property
    def data(self) -> dict[str, Any]:
        return self.doc.data

    @property
    def worldname(self) -> str:
        return str(self.data.get("worldname") or "").strip()

    @property
    def author(self) -> str:
        return str(self.data.get("author") or "").strip()

    @property
    def publishdate(self) -> str:
        return str(self.data.get("publishdate") or "").strip()

    @property
    def archivedate(self) -> str:
        return str(self.data.get("archivedate") or "").strip()

    @property
    def filesize(self) -> str:
        return str(self.data.get("filesize") or "").strip()

    @property
    def tags(self) -> list[str]:
        t = self.data.get("tags")
        return [str(x) for x in t] if isinstance(t, list) else []

    # --- technical metadata (extracted from the .eden binary by node-mapgen,
    # via admin/core/mapgen.py's meta.json sidecar; absent until a world's map
    # has been generated/regenerated at least once since this feature landed) --
    @property
    def worldformat(self) -> str:
        return str(self.data.get("worldformat") or "").strip()

    @property
    def chunkwidth(self) -> int | None:
        return self.data.get("chunkwidth")

    @property
    def chunkheight(self) -> int | None:
        return self.data.get("chunkheight")

    @property
    def skycolor(self) -> int | None:
        return self.data.get("skycolor")

    @property
    def seed(self) -> int | None:
        return self.data.get("seed")

    @property
    def spawnx(self) -> float | None:
        return self.data.get("spawnx")

    @property
    def spawny(self) -> float | None:
        return self.data.get("spawny")

    @property
    def body(self) -> str:
        return self.doc.body

    # --- assets ------------------------------------------------------------
    @property
    def asset_dir(self) -> Path | None:
        return paths.ASSETS_DIR / self.world_id if self.world_id else None

    @property
    def zip_path(self) -> Path | None:
        d = self.asset_dir
        return d / f"{self.world_id}.eden.zip" if d else None

    @property
    def preview_path(self) -> Path | None:
        d = self.asset_dir
        return d / f"{self.world_id}.eden.png" if d else None

    @property
    def map_path(self) -> Path | None:
        d = self.asset_dir
        return d / "map.png" if d else None


def normalize_body(text: str) -> str:
    """Editor text -> the body convention every world file uses: starts with a
    single newline (the separator after the closing `---`), ends with exactly
    one trailing newline."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return f"\n{text}\n" if text.strip() else "\n"


EDITABLE_FIELDS = ("worldname", "author", "publishdate", "archivedate", "filesize")

# Technical fields are machine-extracted (node-mapgen), never hand-edited —
# kept separate from EDITABLE_FIELDS, which drives the manual edit form.
TECHNICAL_FIELDS = (
    "worldformat", "chunkwidth", "chunkheight", "skycolor", "seed", "spawnx", "spawny",
)


def technical_info(w: World) -> dict[str, Any]:
    """Present-only subset of TECHNICAL_FIELDS, or {} if none have been
    extracted yet (map never generated, or generated before this feature)."""
    return {
        key: w.data[key]
        for key in TECHNICAL_FIELDS
        if w.data.get(key) not in (None, "")
    }


def save(w: World, updates: dict[str, Any], body: str | None = None) -> bool:
    """Apply front-matter + body edits and write through frontmatter.save.
    Returns False if nothing actually changed on disk."""
    new_body = None if body is None else normalize_body(body)
    return fm.save(w.md_path, w.doc, updates, new_body)


def load(md_path: Path) -> World:
    md_path = Path(md_path)
    doc = fm.parse(md_path)
    world_id = None
    filename = doc.data.get("filename")
    if isinstance(filename, str):
        m = paths.WORLD_ID_RE.search(filename)
        if m:
            world_id = m.group(1)
    w = World(slug=md_path.stem, md_path=md_path, doc=doc, world_id=world_id)
    w.issues = validate(w)
    return w


def load_all() -> list[World]:
    return [load(p) for p in sorted(paths.WORLDS_DIR.glob("*.md"))]


def validate(w: World) -> list[str]:
    """Same checks (and issue names) as edenadmin.py validate, so the CLI and
    the app agree."""
    issues: list[str] = []
    if w.doc.malformed:
        return ["invalid_front_matter"]

    filename = w.data.get("filename")
    if not filename or not isinstance(filename, str):
        return ["missing_filename"]
    if not w.world_id:
        return ["invalid_filename_format"]

    if not w.asset_dir.exists():
        issues.append("missing_asset_dir")
    if not w.zip_path.exists():
        issues.append("missing_zip")
    if not w.preview_path.exists():
        issues.append("missing_preview")
    if not w.map_path.exists():
        issues.append("missing_map")

    tags = w.data.get("tags")
    if not tags:
        issues.append("missing_tags")
    elif not isinstance(tags, list):
        issues.append("invalid_tags")

    # YAML loads a bare `2011-09-07` as a datetime.date, not a str, so compare on
    # the rendered form. (edenadmin.py's isinstance(pd, str) check flags all 768
    # worlds as invalid for this reason; it just never ran, because PyYAML was
    # never installed.)
    for key, issue in (
        ("publishdate", "invalid_publishdate"),
        ("archivedate", "invalid_archivedate"),
    ):
        value = w.data.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (datetime.date, datetime.datetime)):
            continue
        if not paths.DATE_RE.match(str(value).strip()):
            issues.append(issue)

    return issues
