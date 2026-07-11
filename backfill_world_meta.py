#!/usr/bin/env python3
"""
Backfill technical metadata onto every world's front matter: format (64z/256z),
chunk dimensions, sky color, seed, and spawn coordinates.

These fields are computed by node-mapgen as a side effect of parsing a world
(see node-mapgen/src/World.ts / worldMeta.ts) and written as a meta.json
sidecar next to map.png. The admin app's mapgen job folds that sidecar into
front matter automatically after every map render (admin/app/jobs.py's
_fold_technical_meta) — this script does the same thing in bulk, using
node-mapgen's meta-only CLI (generate-meta.ts) so it doesn't have to
re-render map.png for the ~758 worlds that already have one.

Extracts each world's .eden.zip one at a time into .mapgen-tmp/ (same
lockfile/extraction ladder as generate_missing_maps.py, via admin/core),
runs node-mapgen, folds the result into the world's .md front matter through
admin/core/frontmatter.py's format-preserving writer, then moves on.

Idempotent: skips any world that already has `worldformat` in its front
matter, unless --force is given.

Usage:
    admin/.venv/bin/python backfill_world_meta.py              # all worlds missing tech info
    admin/.venv/bin/python backfill_world_meta.py --dry-run
    admin/.venv/bin/python backfill_world_meta.py --limit 10
    admin/.venv/bin/python backfill_world_meta.py --world-id 1315348100
    admin/.venv/bin/python backfill_world_meta.py --force       # re-extract every world
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from admin.core import mapgen, paths  # noqa: E402
from admin.core import world as world_mod  # noqa: E402

NODE_MAPGEN_DIR = REPO_ROOT / "node-mapgen"
META_DIST = NODE_MAPGEN_DIR / "dist" / "generate-meta.js"
META_SCRIPT = NODE_MAPGEN_DIR / "src" / "generate-meta.ts"
TIMEOUT = 300


def already_processed(w: world_mod.World) -> bool:
    # worldformat is always written whenever meta.json was successfully
    # produced, unlike spawnx/spawny which are legitimately absent for worlds
    # with no home point set — a reliable "already backfilled" marker.
    return bool(w.data.get("worldformat"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="list worlds that would be processed")
    ap.add_argument("--limit", type=int, help="process at most N worlds")
    ap.add_argument("--world-id", help="process one specific world")
    ap.add_argument("--force", action="store_true", help="reprocess worlds that already have technical info")
    args = ap.parse_args()

    node = shutil.which("node")
    if node is None:
        print("ERROR: node not found on PATH", file=sys.stderr)
        return 1

    use_dist = META_DIST.exists()
    if not use_dist and shutil.which("npx") is None:
        print(
            "ERROR: node-mapgen not built and npx not found. "
            "Run: cd node-mapgen && npm install && npx tsc",
            file=sys.stderr,
        )
        return 1

    worlds = world_mod.load_all()
    if args.world_id:
        worlds = [w for w in worlds if w.world_id == args.world_id]
    if not args.force:
        worlds = [w for w in worlds if not already_processed(w)]
    worlds = [w for w in worlds if w.world_id and w.zip_path and w.zip_path.exists()]
    if args.limit:
        worlds = worlds[: args.limit]

    print(f"{len(worlds)} world(s) to process")
    if args.dry_run:
        for w in worlds:
            print(f"  {w.world_id}  {w.worldname}")
        return 0
    if not worlds:
        return 0

    try:
        mapgen.acquire_lock()
    except mapgen.MapgenLockedError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    ok = fail = skipped = 0
    try:
        for w in worlds:
            mapgen.clear_temp_dir()
            paths.TEMP_DIR.mkdir(exist_ok=True)

            pf = mapgen.preflight(w.zip_path)
            if pf.verdict == "too_large":
                print(f"  {w.world_id}: skip (too large for node-mapgen)")
                skipped += 1
                continue

            eden_file = mapgen.extract_eden(w.zip_path, paths.TEMP_DIR)
            if eden_file is None:
                print(f"  {w.world_id}: FAILED (no .eden payload found in zip)")
                fail += 1
                continue

            meta_path = w.asset_dir / mapgen.META_SIDECAR_NAME
            cmd = (
                [node, str(META_DIST)] if use_dist else ["npx", "ts-node", str(META_SCRIPT)]
            ) + [str(eden_file), str(meta_path)]
            try:
                result = subprocess.run(
                    cmd, cwd=str(NODE_MAPGEN_DIR), capture_output=True, text=True, timeout=TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                print(f"  {w.world_id}: FAILED (timed out after {TIMEOUT}s)")
                fail += 1
                continue

            if result.returncode != 0:
                error_class = mapgen.classify_error(result.stderr, result.returncode)
                if error_class == "too_large":
                    print(f"  {w.world_id}: skip (too large for node-mapgen, undetected by preflight)")
                    skipped += 1
                else:
                    print(f"  {w.world_id}: FAILED — {result.stderr.strip()[-200:]}")
                    fail += 1
                continue

            meta = mapgen.read_meta_sidecar(w.world_id)
            updates = mapgen.frontmatter_updates_from_meta(meta) if meta else {}
            if not updates:
                print(f"  {w.world_id}: no technical fields extracted")
                fail += 1
                continue

            world_mod.save(w, updates)
            print(f"  {w.world_id}: {updates.get('worldformat')}, "
                  f"{updates.get('chunkwidth')}x{updates.get('chunkheight')} chunks")
            ok += 1
    finally:
        mapgen.clear_temp_dir()
        mapgen.release_lock()

    print(f"done: {ok} updated, {fail} failed, {skipped} skipped (too large)")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
