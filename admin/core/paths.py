"""Canonical locations inside the archive repo.

Every write path in the admin app is validated against the directories declared
here; nothing outside them is ever touched.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

WORLDS_DIR = REPO_ROOT / "_worlds"
ARTICLES_DIR = REPO_ROOT / "_articles"
POSTS_DIR = REPO_ROOT / "_posts"
ASSETS_DIR = REPO_ROOT / "assets" / "worldfiles"

NODE_MAPGEN_DIR = REPO_ROOT / "node-mapgen"
MAPGEN_DIST = NODE_MAPGEN_DIR / "dist" / "generate-map.js"
TEMP_DIR = REPO_ROOT / ".mapgen-tmp"

RUNTIME_DIR = REPO_ROOT / "admin" / ".runtime"
INDEX_DB = RUNTIME_DIR / "index.db"
BACKUP_DIR = RUNTIME_DIR / "backups"
UPLOAD_DIR = RUNTIME_DIR / "uploads"

# Committed, so the gitignored SQLite index stays safely disposable.
DISMISSALS_FILE = REPO_ROOT / "admin" / "dupe_dismissals.yaml"

WORLD_ID_RE = re.compile(r"(\d{10,})\.eden$")
WORLD_ID_ONLY_RE = re.compile(r"^\d{10,}$")
SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Directories the app is allowed to write into.
WRITABLE_ROOTS = (WORLDS_DIR, ARTICLES_DIR, POSTS_DIR, ASSETS_DIR, RUNTIME_DIR, TEMP_DIR)


def ensure_runtime_dirs() -> None:
    for d in (RUNTIME_DIR, BACKUP_DIR, UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)


def is_writable_path(path: Path) -> bool:
    """True only if `path` resolves inside one of the WRITABLE_ROOTS."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return any(
        resolved == root or root in resolved.parents for root in WRITABLE_ROOTS
    )


def assert_writable(path: Path) -> Path:
    if not is_writable_path(path):
        raise ValueError(f"refusing to write outside the archive: {path}")
    return Path(path)


def asset_dir_for(world_id: str) -> Path:
    if not WORLD_ID_ONLY_RE.match(world_id):
        raise ValueError(f"invalid world id: {world_id!r}")
    return ASSETS_DIR / world_id


def world_md_for(slug: str) -> Path:
    if not SLUG_RE.match(slug) or ".." in slug:
        raise ValueError(f"invalid slug: {slug!r}")
    return WORLDS_DIR / f"{slug}.md"
