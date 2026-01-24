#!/usr/bin/env python3
import argparse
import datetime
import os
import re
import shutil
import zipfile
from pathlib import Path
import urllib.request
import subprocess

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
PREVIEW_BASE_URL = "http://files.edengame.net"

# ----------------------------
# Helpers
# ----------------------------

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "-", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")

def bytes_to_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024*1024):.1f} MB"

def prompt_optional(label: str, suggested: str | None = None):
    if suggested:
        val = input(f"{label} [{suggested}]: ").strip()
        return val if val else suggested
    else:
        val = input(f"{label} (optional): ").strip()
        return val if val else None

def is_real_file(path: Path) -> bool:
    return not path.name.startswith("._") and "__MACOSX" not in path.parts

def parse_new_naming_convention(file_path: Path):
    """
    Attempts to parse:
    <world name> <10+ digit id> <tags>.eden(.zip)
    Returns (worldname, world_id, tags) or (None, None, None)
    """
    name = file_path.stem
    # if .eden.zip, remove extra .eden
    if name.endswith(".eden"):
        name = Path(name).stem

    match = re.search(r"\b(\d{10,})\b", name)
    if not match:
        return None, None, None

    world_id = match.group(1)
    before = name[:match.start()].strip()
    after = name[match.end():].strip()

    worldname = before if before else None
    tags = [t for t in re.split(r"[,\s]+", after) if t] if after else []

    return worldname, world_id, tags

# ----------------------------
# Preview
# ----------------------------

def download_preview(world_id: str, dest_path: Path):
    url = f"{PREVIEW_BASE_URL}/{world_id}.eden.png"
    try:
        urllib.request.urlretrieve(url, dest_path)
        print(f"✔ Preview downloaded from {url}")
        return True
    except:
        print(f"⚠ No preview found at {url}, skipping")
        return False

# ----------------------------
# Map generation
# ----------------------------

def generate_map_for_world(eden_file: Path, output_dir: Path):
    try:
        subprocess.run(
            ["npx", "ts-node", "node-mapgen/src/generate-map.ts",
             str(eden_file), str(output_dir)],
            check=False
        )
    except Exception as e:
        print(f"⚠ Map generation error for {eden_file.name}: {e}")

# ----------------------------
# Compression
# ----------------------------

def compress_eden_to_zip(eden_path: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.write(eden_path, eden_path.name)

# ----------------------------
# Import logic
# ----------------------------

def import_one_file(file_path: Path):
    file_path = file_path.resolve()

    parsed_name, parsed_id, parsed_tags = parse_new_naming_convention(file_path)

    # ---- World name prompt ----
    if parsed_name:
        worldname = input(f"World name [{parsed_name}]: ").strip() or parsed_name
    else:
        worldname = input(f"World name for {file_path.name}: ").strip()

    if not worldname:
        print(f"⚠ World name empty, skipping {file_path}")
        return "failed"

    archivedate = prompt_optional("Archive date (YYYY-MM-DD)")
    author = prompt_optional("Author")

    # ---- Tags prompt with autofill ----
    if parsed_tags:
        suggested_tags = ", ".join(parsed_tags)
        tags_raw = prompt_optional("Tags (comma separated)", suggested_tags)
    else:
        tags_raw = prompt_optional("Tags (comma separated)")

    tags = [t for t in re.split(r"[,\s]+", tags_raw) if t] if tags_raw else []

    extract_dir = Path("/tmp") / f"eden_extract_{os.getpid()}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    eden_file = None
    image_candidates = []

    try:
        # --- ZIP or raw eden ---
        try:
            with zipfile.ZipFile(file_path, 'r') as z:
                found = False
                for info in z.infolist():
                    name = Path(info.filename)
                    if name.suffix.lower() == ".eden" and is_real_file(name):
                        eden_file = Path(z.extract(info, extract_dir)).resolve()
                        found = True
                    elif name.suffix.lower() in IMAGE_EXTS and is_real_file(name):
                        image_candidates.append(Path(z.extract(info, extract_dir)).resolve())
                if not found:
                    # No .eden inside, treat as raw
                    eden_file = file_path
        except zipfile.BadZipFile:
            # Treat any .eden or .eden.zip as raw .eden
            if file_path.suffix.lower() in {".eden", ".zip"}:
                eden_file = file_path
            else:
                print(f"⚠ Unknown file type {file_path}, skipping")
                shutil.rmtree(extract_dir)
                return "failed"

        if eden_file is None:
            print(f"⚠ No .eden file found in {file_path}, skipping")
            shutil.rmtree(extract_dir)
            return "failed"

        # --- World ID ---
        if parsed_id:
            world_id = parsed_id
        else:
            match = re.search(r"(\d{10,})\.eden$", eden_file.name)
            if not match:
                print(f"⚠ Cannot determine numeric ID from {eden_file.name}, skipping")
                shutil.rmtree(extract_dir)
                return "failed"
            world_id = match.group(1)

        publish_date = datetime.date.fromtimestamp(int(world_id)).isoformat()
        filesize = bytes_to_mb(eden_file.stat().st_size)

        asset_dir = Path("assets/worldfiles") / world_id
        asset_dir.mkdir(parents=True, exist_ok=True)

        # Always store as <world_id>.eden.zip
        zip_dest = asset_dir / f"{world_id}.eden.zip"
        compress_eden_to_zip(eden_file, zip_dest)

        if image_candidates:
            chosen_map = max(image_candidates, key=lambda p: p.stat().st_size)
            shutil.copy2(chosen_map, asset_dir / "map.png")

        preview_path = asset_dir / f"{world_id}.eden.png"
        download_preview(world_id, preview_path)

        (asset_dir / worldname).touch()

        slug = slugify(worldname)
        md_path = Path("_worlds") / f"{slug}.md"

        if not md_path.exists():
            fm = [
                "---",
                "layout: page",
                f"filename: {world_id}.eden",
                f"worldname: {worldname}",
                f"publishdate: {publish_date}",
                f"archivedate: {archivedate or ''}",
                f'filesize: "{filesize}"',
                f"author: {author or ''}",
                "tags:",
            ]
            for tag in tags:
                fm.append(f"  - {tag}")
            fm.extend([
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
                ""
            ])
            md_path.write_text("\n".join(fm), encoding="utf-8")

        shutil.rmtree(extract_dir)
        print(f"✅ World imported: {worldname}")
        return "success"

    except Exception as e:
        shutil.rmtree(extract_dir)
        print(f"⚠ Failed {file_path}: {e}")
        return "failed"

# ----------------------------
# Main
# ----------------------------

def main():
    parser = argparse.ArgumentParser(description="Add Eden worlds (batch-ready)")
    parser.add_argument("--eden", nargs="*", help="Path(s) to .zip/.eden files")
    parser.add_argument("--folder", help="Folder containing multiple worlds")
    args = parser.parse_args()

    files = []
    if args.eden:
        files.extend(Path(p).resolve() for p in args.eden)
    if args.folder:
        folder = Path(args.folder).resolve()
        files.extend(sorted(folder.glob("*")))

    if not files:
        print("⚠ No files provided")
        return

    summary = {"success":0, "skipped":0, "failed":0}
    for f in files:
        result = import_one_file(f)
        if result:
            summary[result] += 1

    print("\nBatch complete:")
    print(f"✅ Success: {summary['success']}")
    print(f"⏭ Skipped: {summary['skipped']}")
    print(f"⚠ Failed: {summary['failed']}")

if __name__ == "__main__":
    main()
