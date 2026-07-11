"""Staged world upload: parse -> hash + similarity check -> commit.

De-interactivized port of z_add_world.py:import_one_file() — every input()
prompt is gone; the archivist supplies worldname/author/tags/archivedate
through the upload review form instead, pre-filled with whatever
parse_naming_convention() parses out of the filename (the same convention
z_add_world.py already understands: `<world name> <10+ digit id> <tags>.eden(.zip)`).

Two phases, matching ADMIN_APP_PLAN.md's upload flow:
  1. stage() — read-only. Extracts the .eden payload into a private staging
     dir under admin/.runtime/uploads/, computes both hash tiers, and
     returns a StagedImport. Writes nothing into the archive.
  2. commit() — writes the world: asset dir, {id}.eden.zip (freshly
     recompressed from the raw .eden, same as z_add_world.py — this is why
     new imports are always the "standard" raw-in-zip packaging, not the
     gzip-packaged form most existing downloads use), an optional bundled
     map.png, a best-effort preview download, and _worlds/{slug}.md. Never
     overwrites an existing .md for the same slug (matches z_add_world.py).

check_against_archive() is the "Upload-time check" from the plan: world ID
already archived is a hard block (return early, nothing else is computed);
payload/zip hash matches and near-name/version-chain matches are soft
warnings the archivist can pass by confirming.
"""
from __future__ import annotations

import datetime
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from . import hashing
from . import index as index_mod
from . import paths
from . import world as world_mod

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_BASE_URL = "http://files.edengame.net"
NAMING_ID_RE = re.compile(r"\b(\d{10,})\b")
NEAR_NAME_CUTOFF = 0.75  # looser than dupes.py's 0.87 — a softer, earlier nudge


class ImporterError(ValueError):
    pass


def _is_real_file(name: Path) -> bool:
    return not name.name.startswith("._") and "__MACOSX" not in name.parts


def parse_naming_convention(filename: str) -> tuple[str | None, str | None, list[str]]:
    """`<world name> <10+ digit id> <tags>.eden(.zip)` -> (worldname, world_id, tags)."""
    stem = Path(filename).stem
    if stem.endswith(".eden"):
        stem = Path(stem).stem
    m = NAMING_ID_RE.search(stem)
    if not m:
        return None, None, []
    world_id = m.group(1)
    before = stem[: m.start()].strip()
    after = stem[m.end() :].strip()
    worldname = before or None
    tags = [t for t in re.split(r"[,\s]+", after) if t] if after else []
    return worldname, world_id, tags


@dataclass
class StagedImport:
    token: str  # opaque id — the staged file's name under UPLOAD_DIR, minus extension
    staged_path: Path
    original_filename: str
    eden_path: Path | None
    preview_paths: list[Path] = field(default_factory=list)
    world_id: str | None = None
    worldname: str | None = None
    tags: list[str] = field(default_factory=list)
    publishdate: str | None = None
    filesize: str | None = None
    zip_sha256: str = ""
    payload_sha256: str | None = None
    payload_error: str | None = None
    error: str | None = None


def receive_upload(data: bytes, original_filename: str) -> str:
    """Writes uploaded bytes to a fresh file under UPLOAD_DIR. Returns the
    token (filename, no extension) used to re-locate it for staging/commit."""
    paths.ensure_runtime_dirs()
    import uuid

    token = uuid.uuid4().hex[:12]
    suffix = Path(original_filename).suffix or ".zip"
    dest = paths.UPLOAD_DIR / f"{token}{suffix}"
    dest.write_bytes(data)
    return token


def _find_staged_file(token: str) -> Path:
    if not re.match(r"^[0-9a-f]{12}$", token):
        raise ImporterError("invalid upload token")
    matches = list(paths.UPLOAD_DIR.glob(f"{token}.*"))
    if not matches:
        raise ImporterError("staged upload not found — it may have already been discarded")
    return matches[0]


def stage(token: str, original_filename: str) -> StagedImport:
    """Read-only: parse the staged file, extract its .eden payload into a
    private subdirectory, compute hashes."""
    staged_path = _find_staged_file(token)
    parsed_name, parsed_id, parsed_tags = parse_naming_convention(original_filename)

    stage_dir = paths.UPLOAD_DIR / f"{token}-extracted"
    stage_dir.mkdir(exist_ok=True)

    eden_path: Path | None = None
    preview_paths: list[Path] = []

    try:
        with zipfile.ZipFile(staged_path, "r") as z:
            for info in z.infolist():
                name = Path(info.filename)
                if not _is_real_file(name):
                    continue
                if name.suffix.lower() == ".eden":
                    eden_path = Path(z.extract(info, stage_dir)).resolve()
                elif name.suffix.lower() in IMAGE_EXTS:
                    preview_paths.append(Path(z.extract(info, stage_dir)).resolve())
        if eden_path is None:
            eden_path = staged_path  # no .eden entry inside; treat the whole thing as raw
    except zipfile.BadZipFile:
        eden_path = staged_path  # not a real zip — raw .eden, or a bare gzip stream

    world_id = parsed_id
    if world_id is None and eden_path is not None:
        m = paths.WORLD_ID_RE.search(eden_path.name)
        if m:
            world_id = m.group(1)

    publishdate = None
    if world_id:
        try:
            publishdate = datetime.date.fromtimestamp(int(world_id)).isoformat()
        except (ValueError, OSError, OverflowError):
            publishdate = None

    filesize = None
    if eden_path and eden_path.exists() and eden_path.is_file():
        filesize = world_mod.bytes_to_mb(eden_path.stat().st_size)

    zip_sha256 = hashing.hash_zip_bytes(staged_path)
    payload = hashing.hash_payload(staged_path)

    error = None
    if world_id is None:
        error = "could not determine a numeric world ID from the filename"

    return StagedImport(
        token=token, staged_path=staged_path, original_filename=original_filename,
        eden_path=eden_path, preview_paths=preview_paths,
        world_id=world_id, worldname=parsed_name, tags=parsed_tags,
        publishdate=publishdate, filesize=filesize,
        zip_sha256=zip_sha256, payload_sha256=payload.sha256, payload_error=payload.error,
        error=error,
    )


def discard(token: str) -> None:
    for p in paths.UPLOAD_DIR.glob(f"{token}*"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


@dataclass
class UploadWarning:
    kind: str  # already_archived | identical_payload | identical_zip | similar_name
    slug: str
    worldname: str
    detail: str
    blocking: bool


def check_against_archive(staged: StagedImport, conn) -> list[UploadWarning]:
    """Read-only. `conn` is the admin app's SQLite index connection."""
    warnings: list[UploadWarning] = []

    if staged.world_id:
        existing = index_mod.get_by_world_id(conn, staged.world_id)
        if existing:
            return [
                UploadWarning(
                    "already_archived", existing["slug"], existing["worldname"] or existing["slug"],
                    f"world id {staged.world_id} is already archived", blocking=True,
                )
            ]

    if staged.payload_sha256:
        row = conn.execute(
            "SELECT slug, worldname FROM worlds WHERE payload_sha256=?", (staged.payload_sha256,)
        ).fetchone()
        if row:
            warnings.append(
                UploadWarning(
                    "identical_payload", row["slug"], row["worldname"] or row["slug"],
                    "byte-identical world payload", blocking=False,
                )
            )

    if not any(w.kind == "identical_payload" for w in warnings) and staged.zip_sha256:
        row = conn.execute(
            "SELECT slug, worldname FROM worlds WHERE zip_sha256=?", (staged.zip_sha256,)
        ).fetchone()
        if row:
            warnings.append(
                UploadWarning(
                    "identical_zip", row["slug"], row["worldname"] or row["slug"],
                    "identical download", blocking=False,
                )
            )

    if staged.worldname:
        norm = world_mod.normalize_name(staged.worldname)
        base, _ = world_mod.strip_version(norm)
        for r in conn.execute("SELECT slug, worldname, norm_name, base_name FROM worlds"):
            if not r["norm_name"]:
                continue
            if base and r["base_name"] == base:
                warnings.append(
                    UploadWarning(
                        "similar_name", r["slug"], r["worldname"] or r["slug"],
                        f"same base name {base!r} — likely a version chain", blocking=False,
                    )
                )
                continue
            ratio = SequenceMatcher(None, norm, r["norm_name"]).ratio()
            if ratio >= NEAR_NAME_CUTOFF:
                warnings.append(
                    UploadWarning(
                        "similar_name", r["slug"], r["worldname"] or r["slug"],
                        f"{ratio:.2f} name similarity", blocking=False,
                    )
                )

    return warnings


def _render_new_world_md(
    *, worldname: str, world_id: str, publishdate: str, archivedate: str,
    filesize: str, author: str, tags: list[str],
) -> str:
    """Byte-for-byte the same hand-written shape z_add_world.py emits —
    intentionally not routed through frontmatter.render(), since this is a
    brand new file, not an edit to an existing one."""
    lines = [
        "---", "layout: page", f"filename: {world_id}.eden", f"worldname: {worldname}",
        f"publishdate: {publishdate}", f"archivedate: {archivedate}",
        f'filesize: "{filesize}"', f"author: {author}", "tags:",
    ]
    lines.extend(f"  - {t}" for t in tags)
    lines.extend([
        "---",
        f"## {worldname}",
        "",
        "There may be an article available for this world. Check back soon!",
        "",
        f"![Preview Image]({{{{ site.baseurl }}}}/assets/worldfiles/{world_id}/{world_id}.eden.png)",
        "",
        "{% include world-details.html %}",
        "",
        "{% include world-download.html %}",
        "",
        "Note: World downloads are compressed, and must be unzipped before played.",
        "",
        "## Map",
        "",
        f"![Map]({{{{ site.baseurl }}}}/assets/worldfiles/{world_id}/map.png)",
        "",
    ])
    return "\n".join(lines)


def _try_download_preview(world_id: str, dest: Path) -> bool:
    import requests

    url = f"{PREVIEW_BASE_URL}/{world_id}.eden.png"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except requests.RequestException:
        return False


def commit(
    staged: StagedImport, *, worldname: str, author: str, archivedate: str, tags: list[str],
) -> str:
    """Writes the world into the archive. Returns the new slug. Raises
    ImporterError without writing anything if the staged import is unusable."""
    if staged.error:
        raise ImporterError(staged.error)
    if not staged.world_id:
        raise ImporterError("no world id")
    if not staged.eden_path or not staged.eden_path.exists():
        raise ImporterError("no .eden payload found in the upload")
    worldname = worldname.strip()
    if not worldname:
        raise ImporterError("world name is required")

    world_id = staged.world_id
    asset_dir = paths.assert_writable(paths.ASSETS_DIR / world_id)
    asset_dir.mkdir(parents=True, exist_ok=True)

    zip_dest = paths.assert_writable(asset_dir / f"{world_id}.eden.zip")
    with zipfile.ZipFile(zip_dest, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(staged.eden_path, staged.eden_path.name)

    if staged.preview_paths:
        chosen = max(staged.preview_paths, key=lambda p: p.stat().st_size)
        shutil.copy2(chosen, paths.assert_writable(asset_dir / "map.png"))

    _try_download_preview(world_id, paths.assert_writable(asset_dir / f"{world_id}.eden.png"))

    # Stray 0-byte marker file z_add_world.py has always produced — kept for
    # parity with the rest of the corpus (see ADMIN_APP_PLAN.md open item 4).
    paths.assert_writable(asset_dir / worldname).touch()

    slug = world_mod.slugify(worldname)
    md_path = paths.assert_writable(paths.WORLDS_DIR / f"{slug}.md")
    if not md_path.exists():
        text = _render_new_world_md(
            worldname=worldname, world_id=world_id, publishdate=staged.publishdate or "",
            archivedate=archivedate.strip(), filesize=staged.filesize or "",
            author=author.strip(), tags=tags,
        )
        md_path.write_text(text, encoding="utf-8", newline="\n")

    discard(staged.token)
    return slug
