#!/usr/bin/env python3
"""
Batch-generate missing top-down map PNGs for all worlds in the archive.

Scans _worlds/*.md, finds entries where assets/worldfiles/{id}/map.png is
absent, extracts each .eden.zip one at a time into .mapgen-tmp/, runs the
node-mapgen TypeScript tool to render the PNG, then immediately deletes the
extracted .eden file before moving on.

Usage:
    python3 generate_missing_maps.py              # generate all missing maps
    python3 generate_missing_maps.py --dry-run    # list which maps are missing
    python3 generate_missing_maps.py --limit 10   # process at most 10 worlds
    python3 generate_missing_maps.py --world-id 1315348100  # one specific world
"""
import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
WORLDS_DIR = REPO_ROOT / "_worlds"
ASSETS_DIR = REPO_ROOT / "assets" / "worldfiles"
MAPGEN_DIST = REPO_ROOT / "node-mapgen" / "dist" / "generate-map.js"
MAPGEN_SCRIPT = REPO_ROOT / "node-mapgen" / "src" / "generate-map.ts"
TEMP_DIR = REPO_ROOT / ".mapgen-tmp"
WORLD_ID_RE = re.compile(r"(\d{10,})\.eden$")


def get_world_id(md_path: Path) -> str | None:
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            m = WORLD_ID_RE.search(line)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def clear_temp_dir():
    if TEMP_DIR.exists():
        for f in TEMP_DIR.iterdir():
            try:
                f.unlink()
            except Exception:
                pass


def _is_junk(filename: str) -> bool:
    name = Path(filename).name
    return filename.startswith("__MACOSX") or name.startswith("._")


def _real_entries(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [e for e in z.infolist() if not _is_junk(e.filename)]


def _extract_eden(zip_path: Path, dest: Path) -> Path | None:
    """
    Extract a world .eden file from a zip archive.

    Handles three packaging patterns found in the archive:
      1. zip -> raw .eden file
      2. zip -> gzip-compressed file named .eden or .eden.zip (World.ts handles gzip)
      3. zip -> zip -> .eden (double-nested)
    """
    if not zipfile.is_zipfile(zip_path):
        return None

    with zipfile.ZipFile(zip_path, "r") as z:
        entries = _real_entries(z)
        if not entries:
            return None

        # Prefer an explicit .eden entry
        eden_entry = next(
            (e for e in entries if e.filename.lower().endswith(".eden")), None
        )
        if eden_entry:
            z.extract(eden_entry, dest)
            result = next(dest.rglob(Path(eden_entry.filename).name), None)
            return result or next(dest.rglob("*.eden"), None)

        # .eden.zip entry: may be a gzip-compressed .eden (node-mapgen handles gzip)
        # or a real zip containing the .eden.
        eden_zip_entry = next(
            (e for e in entries if e.filename.lower().endswith(".eden.zip")), None
        )
        if eden_zip_entry:
            extracted = dest / Path(eden_zip_entry.filename).name
            z.extract(eden_zip_entry, dest)
            if not extracted.exists():
                extracted = next(dest.rglob("*.eden.zip"), None)
            if not extracted:
                return None
            # Check if it's an actual zip (real nested zip) or just a gzip/raw .eden
            if zipfile.is_zipfile(extracted):
                return _extract_eden(extracted, dest)
            # It's a gzip or raw .eden -- rename to .eden so node-mapgen sees it
            renamed = extracted.with_suffix("").with_suffix(".eden")
            extracted.rename(renamed)
            return renamed

        # Last resort: take any single large file and try it
        if len(entries) == 1:
            z.extract(entries[0], dest)
            extracted = next(dest.rglob(Path(entries[0].filename).name), None)
            if extracted and zipfile.is_zipfile(extracted):
                return _extract_eden(extracted, dest)
            return extracted

    return None


def find_zip(world_id: str) -> Path | None:
    """Return the zip for a world, falling back to any *.zip in the asset dir."""
    standard = ASSETS_DIR / world_id / f"{world_id}.eden.zip"
    if standard.exists():
        return standard
    asset_dir = ASSETS_DIR / world_id
    if asset_dir.is_dir():
        candidates = sorted(asset_dir.glob("*.zip")) + sorted(asset_dir.glob("*.eden.zip"))
        if candidates:
            return candidates[0]
    return None


def generate_map(world_id: str) -> bool:
    zip_path = find_zip(world_id)
    map_path = ASSETS_DIR / world_id / "map.png"

    if zip_path is None:
        print(f"  ⚠ No zip found for {world_id}")
        return False

    clear_temp_dir()
    try:
        eden_file = _extract_eden(zip_path, TEMP_DIR)
        if eden_file is None:
            print(f"  ⚠ No .eden found in {zip_path.name}")
            return False

        result = subprocess.run(
            (["node", str(MAPGEN_DIST)] if MAPGEN_DIST.exists()
             else ["npx", "ts-node", str(MAPGEN_SCRIPT)]) + [str(eden_file), str(map_path)],
            cwd=str(REPO_ROOT / "node-mapgen"),
            capture_output=True,
            text=True,
            timeout=180,
        )

        if result.returncode == 0:
            print(f"  ✔ {world_id}")
            return True
        else:
            stderr = result.stderr.strip()
            # ts-node sometimes prints the error on stdout
            msg = (stderr or result.stdout.strip())[:200]
            print(f"  ⚠ {world_id}: {msg}")
            return False

    except subprocess.TimeoutExpired:
        print(f"  ⚠ {world_id}: timed out after 180s")
        return False
    except Exception as e:
        print(f"  ⚠ {world_id}: {e}")
        return False
    finally:
        clear_temp_dir()


def find_missing(target_id: str | None = None) -> list[str]:
    missing = []
    for md in sorted(WORLDS_DIR.glob("*.md")):
        world_id = get_world_id(md)
        if not world_id:
            continue
        if target_id and world_id != target_id:
            continue
        map_path = ASSETS_DIR / world_id / "map.png"
        if not map_path.exists():
            missing.append(world_id)
    return missing


def main():
    parser = argparse.ArgumentParser(
        description="Generate missing top-down map PNGs for edenarchive worlds"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List worlds missing map.png without generating anything"
    )
    parser.add_argument(
        "--limit", type=int, metavar="N",
        help="Process at most N worlds"
    )
    parser.add_argument(
        "--world-id", metavar="ID",
        help="Process a single world by numeric ID"
    )
    args = parser.parse_args()

    if not WORLDS_DIR.exists():
        print(f"ERROR: _worlds/ directory not found at {WORLDS_DIR}", file=sys.stderr)
        sys.exit(1)

    if not MAPGEN_DIST.exists() and not MAPGEN_SCRIPT.exists():
        print(f"ERROR: node-mapgen not found. Run: cd node-mapgen && npm install && npx tsc", file=sys.stderr)
        sys.exit(1)

    missing = find_missing(target_id=args.world_id)
    total_worlds = sum(1 for _ in WORLDS_DIR.glob("*.md"))
    print(f"Worlds in archive: {total_worlds}")
    print(f"Missing map.png:   {len(missing)}")

    if args.dry_run:
        if missing:
            print("\nWorlds missing map.png:")
            for wid in missing:
                print(f"  {wid}")
        return

    if not missing:
        print("Nothing to do.")
        return

    to_process = missing[: args.limit] if args.limit else missing
    if args.limit and len(missing) > args.limit:
        print(f"Processing first {args.limit} of {len(missing)}")

    TEMP_DIR.mkdir(exist_ok=True)
    ok = fail = 0
    try:
        for world_id in to_process:
            success = generate_map(world_id)
            if success:
                ok += 1
            else:
                fail += 1
    finally:
        clear_temp_dir()

    print(f"\nDone: {ok} generated, {fail} failed")


if __name__ == "__main__":
    main()
