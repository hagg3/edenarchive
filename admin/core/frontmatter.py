"""Format-preserving front-matter parse/render.

The world files were hand-emitted by z_add_world.py, not by a YAML library, and
the corpus depends on those exact bytes: empty scalars are written `key: ` with a
trailing space, `filesize` is always double-quoted, tags are 2-space block
sequences. Running yaml.safe_dump over a world file rewrites all of that (this is
what z_scripts/tag manage/merge_tags.py does today, and why it corrupts files).

So: yaml.safe_load is used only to *read* values. Writing edits the original
lines in place and leaves every untouched line byte-identical.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import paths

CANONICAL_ORDER = [
    "layout",
    "filename",
    "worldname",
    "publishdate",
    "archivedate",
    "filesize",
    "author",
    "tags",
]

ALWAYS_QUOTED = {"filesize"}

DELIM = "---"

# Sentinel meaning "remove this key entirely".
DELETE = object()


class FrontMatterError(ValueError):
    pass


@dataclass
class Document:
    """A parsed markdown file with its front matter kept verbatim."""

    path: Path
    fm_lines: list[str]  # front-matter lines, no delimiters, no trailing newlines
    body: str  # everything after the closing delimiter, byte-for-byte
    data: dict[str, Any] = field(default_factory=dict)  # yaml.safe_load view
    # True when the front matter is not valid YAML (e.g. _articles/creatures.md
    # has a bare text line in it). The lines are still preserved verbatim, so the
    # file round-trips; `data` is empty and the app flags it for repair.
    malformed: bool = False
    error: str = ""

    @property
    def key_order(self) -> list[str]:
        return [k for k, _ in _scalar_positions(self.fm_lines)]


def _split_key(line: str) -> str | None:
    """Return the key of a top-level `key: value` line, else None."""
    if not line or line[0] in " \t#":
        return None
    key, sep, _ = line.partition(":")
    if not sep or not key or key != key.strip():
        return None
    return key


def _scalar_positions(fm_lines: list[str]) -> list[tuple[str, int]]:
    """[(key, line_index)] for every top-level key in file order."""
    out = []
    for i, line in enumerate(fm_lines):
        key = _split_key(line)
        if key is not None:
            out.append((key, i))
    return out


def _block_end(fm_lines: list[str], start: int) -> int:
    """Exclusive end index of the key at `start`, including its indented block."""
    i = start + 1
    while i < len(fm_lines):
        line = fm_lines[i]
        if line.strip() == "" or line.startswith((" ", "\t", "-")):
            i += 1
            continue
        break
    return i


def parse(path: Path) -> Document:
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith(DELIM):
        raise FrontMatterError(f"no front matter: {path}")

    lines = text.split("\n")
    try:
        end = next(
            i for i in range(1, len(lines)) if lines[i].rstrip() == DELIM
        )
    except StopIteration:
        raise FrontMatterError(f"unterminated front matter: {path}") from None

    fm_lines = lines[1:end]
    # Rejoin the remainder exactly as it was, including its leading newline.
    body = "\n".join(lines[end + 1 :])
    if lines[end + 1 :]:
        body = "\n" + body

    malformed = False
    error = ""
    try:
        data = yaml.safe_load("\n".join(fm_lines))
    except yaml.YAMLError as exc:
        data, malformed, error = {}, True, str(exc).replace("\n", " ")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        data, malformed = {}, True
        error = error or "front matter is not a mapping"

    return Document(
        path=Path(path),
        fm_lines=fm_lines,
        body=body,
        data=data,
        malformed=malformed,
        error=error,
    )


def _unchanged(old: Any, new: Any) -> bool:
    """Semantic equality for a scalar, treating None and "" as the same."""
    norm = lambda v: "" if v is None else str(v)  # noqa: E731
    return norm(old) == norm(new)


def _emit_scalar(key: str, value: Any, original: str | None) -> str:
    """One `key: value` line, matching the corpus conventions."""
    if value is None:
        value = ""
    text = str(value)

    quoted = key in ALWAYS_QUOTED
    if original is not None and not quoted:
        _, _, raw = original.partition(":")
        quoted = raw.strip().startswith(('"', "'"))

    if quoted:
        return f'{key}: "{text}"'
    # Empty scalars keep the trailing space the corpus uses (598 `author: ` lines).
    return f"{key}: {text}"


def _emit_tags(tags: list[str]) -> list[str]:
    return ["tags:"] + [f"  - {t}" for t in tags]


def _merge_tags(existing: list[str], new: list[str]) -> list[str]:
    """Preserve existing order; append additions at the end, so a retag is a
    one-line diff rather than a reordering of the whole block."""
    kept = [t for t in existing if t in new]
    added = [t for t in new if t not in existing]
    return kept + added


def render(
    doc: Document, updates: dict[str, Any] | None = None, body: str | None = None
) -> str:
    """Full file text with `updates` applied and everything else untouched.

    render(parse(p), {}) must equal p.read_text() for every file in the corpus.
    `body`, if given, replaces doc.body verbatim (used by the body editor); by
    default the original body passes through byte-for-byte.
    """
    updates = dict(updates or {})
    fm = list(doc.fm_lines)
    positions = dict(_scalar_positions(fm))

    # 1. Rewrite keys that already exist, in place.
    for key in list(updates):
        if key not in positions:
            continue
        value = updates.pop(key)
        idx = positions[key]
        end = _block_end(fm, idx)

        if value is DELETE:
            replacement: list[str] = []
        elif key == "tags":
            existing = doc.data.get("tags") or []
            existing = [str(t) for t in existing] if isinstance(existing, list) else []
            incoming = [str(t) for t in value] if isinstance(value, list) else []
            merged = _merge_tags(existing, incoming)
            # Unchanged: keep the original block verbatim.
            replacement = fm[idx:end] if merged == existing else _emit_tags(merged)
        elif _unchanged(doc.data.get(key), value):
            # One worldname line in the corpus carries a trailing space that YAML
            # strips on load. Re-emitting a semantically identical value would
            # silently normalize bytes like that, so leave the line alone.
            replacement = [fm[idx]]
        else:
            replacement = [_emit_scalar(key, value, fm[idx])]

        fm[idx:end] = replacement
        positions = dict(_scalar_positions(fm))

    # 2. Insert keys that don't exist yet, at their canonical position.
    for key, value in updates.items():
        if value is DELETE:
            continue
        # Setting a key to empty on a file that lacks it is a no-op: never add
        # `archivedate: ` to the 560 short-form files and blow up the diff.
        is_empty = value is None or (isinstance(value, str) and value == "")
        if key == "tags":
            is_empty = not value
        if is_empty:
            continue

        if key == "tags":
            block = _emit_tags([str(t) for t in value])
        else:
            block = [_emit_scalar(key, value, None)]

        insert_at = len(fm)
        if key in CANONICAL_ORDER:
            rank = CANONICAL_ORDER.index(key)
            for existing_key, idx in _scalar_positions(fm):
                if (
                    existing_key in CANONICAL_ORDER
                    and CANONICAL_ORDER.index(existing_key) > rank
                ):
                    insert_at = idx
                    break
        fm[insert_at:insert_at] = block

    return "\n".join([DELIM, *fm, DELIM]) + (doc.body if body is None else body)


def save(
    path: Path,
    doc: Document,
    updates: dict[str, Any] | None = None,
    body: str | None = None,
) -> bool:
    """Backup, then atomically write. Returns False if the bytes are unchanged."""
    path = paths.assert_writable(Path(path))
    text = render(doc, updates, body)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False

    if path.exists():
        paths.ensure_runtime_dirs()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = paths.BACKUP_DIR / f"{path.name}.{stamp}.bak"
        shutil.copy2(path, backup)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return True
