#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

Z_ADD_WORLD = REPO_ROOT / "z_add_world.py"
DOWNLOADER_DIR = REPO_ROOT / "z_AutoDownloader"
FETCH_WORLDS = DOWNLOADER_DIR / "fetch_worlds.py"
WORLDS_LIST = DOWNLOADER_DIR / "worlds.txt"

TAG_DIR = REPO_ROOT / "z_scripts" / "tag manage"
ANALYZE_TAGS = TAG_DIR / "analyze_tags.py"
MERGE_TAGS = TAG_DIR / "merge_tags.py"
TAG_MAP = TAG_DIR / "tag_map.yaml"

WORLDS_DIR = REPO_ROOT / "_worlds"
ASSETS_DIR = REPO_ROOT / "assets" / "worldfiles"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WORLD_ID_RE = re.compile(r"(\d{10,})\.eden$")


def run_script(script_path: Path, args: list[str] | None = None, cwd: Path | None = None):
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=False)


def cmd_download(args: argparse.Namespace):
    if args.list:
        src = Path(args.list).expanduser().resolve()
        if not src.exists():
            print(f"ERROR: list file not found: {src}")
            sys.exit(1)
        DOWNLOADER_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, WORLDS_LIST)
        print(f"Using list: {WORLDS_LIST}")
    run_script(FETCH_WORLDS, cwd=DOWNLOADER_DIR)


def cmd_import(args: argparse.Namespace):
    passthrough = []
    if args.eden:
        passthrough.extend(["--eden", *args.eden])
    if args.folder:
        passthrough.extend(["--folder", args.folder])

    if not passthrough:
        print("ERROR: provide --eden and/or --folder")
        sys.exit(1)

    run_script(Z_ADD_WORLD, args=passthrough, cwd=REPO_ROOT)


def cmd_tags_analyze(args: argparse.Namespace):
    run_script(ANALYZE_TAGS, cwd=TAG_DIR)


def cmd_tags_merge(args: argparse.Namespace):
    if not TAG_MAP.exists():
        print(f"ERROR: tag map not found: {TAG_MAP}")
        sys.exit(1)
    run_script(MERGE_TAGS, cwd=TAG_DIR)


def parse_front_matter(path: Path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, None
    try:
        _, fm_text, body = text.split("---", 2)
    except ValueError:
        return None, None

    try:
        import yaml  # type: ignore
    except Exception:
        print("ERROR: PyYAML is required for validation. Install with: pip install pyyaml")
        sys.exit(1)

    try:
        fm = yaml.safe_load(fm_text)
    except Exception:
        fm = None
    return fm, body


def validate_world(md_path: Path):
    issues = []
    fm, _ = parse_front_matter(md_path)
    if not fm or not isinstance(fm, dict):
        return ["invalid_front_matter"]

    filename = fm.get("filename")
    if not filename or not isinstance(filename, str):
        issues.append("missing_filename")
        return issues

    match = WORLD_ID_RE.search(filename)
    if not match:
        issues.append("invalid_filename_format")
        return issues

    world_id = match.group(1)
    asset_dir = ASSETS_DIR / world_id
    zip_path = asset_dir / f"{world_id}.eden.zip"
    preview_path = asset_dir / f"{world_id}.eden.png"
    map_path = asset_dir / "map.png"

    if not asset_dir.exists():
        issues.append("missing_asset_dir")
    if not zip_path.exists():
        issues.append("missing_zip")
    if not preview_path.exists():
        issues.append("missing_preview")
    if not map_path.exists():
        issues.append("missing_map")

    tags = fm.get("tags")
    if not tags:
        issues.append("missing_tags")
    elif not isinstance(tags, list):
        issues.append("invalid_tags")

    publishdate = fm.get("publishdate")
    if publishdate and (not isinstance(publishdate, str) or not DATE_RE.match(publishdate)):
        issues.append("invalid_publishdate")

    archivedate = fm.get("archivedate")
    if archivedate and archivedate != "" and (
        not isinstance(archivedate, str) or not DATE_RE.match(archivedate)
    ):
        issues.append("invalid_archivedate")

    return issues


def cmd_validate(args: argparse.Namespace):
    if not WORLDS_DIR.exists():
        print(f"ERROR: missing _worlds directory: {WORLDS_DIR}")
        sys.exit(1)

    results = []
    totals = {
        "total_worlds": 0,
        "invalid_front_matter": 0,
        "missing_filename": 0,
        "invalid_filename_format": 0,
        "missing_asset_dir": 0,
        "missing_zip": 0,
        "missing_preview": 0,
        "missing_map": 0,
        "missing_tags": 0,
        "invalid_tags": 0,
        "invalid_publishdate": 0,
        "invalid_archivedate": 0,
    }

    for md in sorted(WORLDS_DIR.glob("*.md")):
        totals["total_worlds"] += 1
        issues = validate_world(md)
        if issues:
            results.append({"file": md.name, "issues": issues})
            for issue in issues:
                if issue in totals:
                    totals[issue] += 1

    print("\nValidation summary:")
    for key, value in totals.items():
        print(f"- {key}: {value}")

    if results:
        print("\nFiles with issues:")
        for entry in results:
            print(f"- {entry['file']}: {', '.join(entry['issues'])}")

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "totals": totals,
            "results": results,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nReport written to: {out_path}")


def build_parser():
    parser = argparse.ArgumentParser(description="Eden Worlds Archive admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_download = sub.add_parser("download", help="Download worlds listed in worlds.txt")
    p_download.add_argument("--list", help="Path to a worlds.txt list (copied into z_AutoDownloader)")
    p_download.set_defaults(func=cmd_download)

    p_import = sub.add_parser("import", help="Import worlds via z_add_world.py")
    p_import.add_argument("--eden", nargs="*", help="One or more .eden/.zip files")
    p_import.add_argument("--folder", help="Folder containing multiple files")
    p_import.set_defaults(func=cmd_import)

    p_tags = sub.add_parser("tags", help="Tag maintenance tools")
    tags_sub = p_tags.add_subparsers(dest="tag_command", required=True)

    p_tags_analyze = tags_sub.add_parser("analyze", help="Analyze similar tags")
    p_tags_analyze.set_defaults(func=cmd_tags_analyze)

    p_tags_merge = tags_sub.add_parser("merge", help="Merge tags using tag_map.yaml")
    p_tags_merge.set_defaults(func=cmd_tags_merge)

    p_validate = sub.add_parser("validate", help="Validate metadata vs assets")
    p_validate.add_argument("--out", help="Write JSON report to a file")
    p_validate.set_defaults(func=cmd_validate)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
